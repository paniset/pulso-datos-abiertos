"""Pulso Castilla y León: bares, restaurantes y cafeterías registrados por municipio, y municipios sin ninguno.

Fuentes:
- Junta de Castilla y León, «Registro de Turismo de Castilla y León» (CC BY 4.0), portal de datos abiertos.
  Solo se descargan columnas sin datos personales (establecimiento, provincia, municipio); nunca nombres, teléfonos ni correos.
- INE, Padrón municipal: cifras oficiales de población a 1 de enero de 2025 (tablas por provincia).
Cada descarga queda registrada con su fecha y huella SHA-256; solo se guardan recuentos por municipio.

    python scripts/pulso_cyl.py --descargar   # descarga y guarda data/cyl-hosteleria.json
    python scripts/pulso_cyl.py               # genera sites/paniset-github-io/site/pulso-castilla-y-leon/
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from factory.indexing import page_metadata  # noqa: E402
from factory.security import protect_html  # noqa: E402
from madrid import atomic_write  # noqa: E402
from pulso_sample import CSS, csv_safe, escape, es_int, es_number, ld_json  # noqa: E402

JCYL = 'analisis.datosabiertos.jcyl.es'
INE = 'servicios.ine.es'
REGISTRY_DATASET = 'https://datosabiertos.jcyl.es/web/jcyl/set/es/turismo/registro-turismo/1284162055979'
REGISTRY_API = f'https://{JCYL}/api/explore/v2.1/catalog/datasets/registro-de-turismo-de-castilla-y-leon'
REGISTRY_CSV = REGISTRY_API + '/exports/csv?select=establecimiento,provincia,municipio&delimiter=%3B'
REGISTRY_PAGE = 'https://analisis.datosabiertos.jcyl.es/explore/dataset/registro-de-turismo-de-castilla-y-leon/'
INE_PAGE = 'https://www.ine.es/dynt3/inebase/es/index.htm?padre=517'
PROVINCES = {'05': ('Ávila', 2858), '09': ('Burgos', 2862), '24': ('León', 2877), '34': ('Palencia', 2888),
             '37': ('Salamanca', 2891), '40': ('Segovia', 2894), '42': ('Soria', 2896), '47': ('Valladolid', 2904),
             '49': ('Zamora', 2906)}
POPULATION_YEAR = 2025
MAX_BYTES = 30_000_000
MUNICIPALITIES = 2248
KINDS = {'Bares': 'bares', 'Restaurantes': 'restaurantes', 'Cafeterías': 'cafeterias'}
# Municipios del registro con otro nombre en el INE (comprobado el 13/11/2026).
ALIASES = {('AVILA', 'MANJABALAGO'): '05119'}
DATA = ROOT / 'data' / 'cyl-hosteleria.json'
OUT = ROOT / 'sites' / 'paniset-github-io' / 'site' / 'pulso-castilla-y-leon'
ORIGIN = 'https://paniset.github.io/pulso-castilla-y-leon/'
CSV_NAME = 'hosteleria-municipios-castilla-y-leon.csv'
LICENSE_DEED = 'https://creativecommons.org/licenses/by/4.0/deed.es'
REPO = 'https://github.com/paniset/pulso-datos-abiertos'
BANDS = [(0, 99, 'Menos de 100'), (100, 499, 'De 100 a 499'), (500, 999, 'De 500 a 999'),
         (1000, 4999, 'De 1.000 a 4.999'), (5000, 10**9, '5.000 o más')]


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, urllib.parse.urlparse(req.full_url).hostname)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url, host):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password:
        raise ValueError(f'Solo recursos HTTPS de {host}')


def fetch(url, host):
    check_url(url, host)
    request = urllib.request.Request(url, headers={'User-Agent': 'WebFactory-Validation/1.0'})
    with urllib.request.build_opener(OfficialRedirect()).open(request, timeout=120) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Respuesta mayor de lo esperado: posible cambio en la fuente')
    return raw


def key(name):
    """Nombre de municipio normalizado: sin tildes, mayúsculas y el artículo final delante («Barraco (El)» -> «EL BARRACO»)."""
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().upper().strip()
    match = re.match(r'^(.*?)\s*(?:,\s*|\(\s*)(LA|EL|LOS|LAS|LO)\s*\)?$', text)
    if match:
        text = f'{match.group(2)} {match.group(1)}'
    return ' '.join(re.sub(r'[^A-Z0-9 ]', ' ', text).split())


def parse_population(tables):
    """{código INE: {'nombre', 'provincia', 'habitantes'}} desde las tablas de padrón por provincia."""
    result = {}
    for code, (province, _) in PROVINCES.items():
        for row in tables[code]:
            if '. Total. Total habitantes' not in row['Nombre']:
                continue
            meta = row['MetaData'][0]
            if len(meta['Codigo']) != 5:
                continue
            if not meta['Codigo'].startswith(code) or row['Data'][0]['Anyo'] != POPULATION_YEAR:
                raise ValueError(f'Padrón inesperado: {meta}')
            result[meta['Codigo']] = {'nombre': meta['Nombre'], 'provincia': province, 'habitantes': int(row['Data'][0]['Valor'])}
    if len(result) != MUNICIPALITIES:
        raise ValueError(f'Se esperaban {MUNICIPALITIES} municipios y hay {len(result)}')
    return dict(sorted(result.items()))


def parse_registry(raw, population):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';')
    if set(reader.fieldnames or []) != {'establecimiento', 'provincia', 'municipio'}:
        raise ValueError('Columnas del registro distintas de las pedidas: no se guarda nada')
    index = {(key(v['provincia']), key(v['nombre'])): code for code, v in population.items()}
    index.update(ALIASES)
    counts = {code: {k: 0 for k in KINDS.values()} for code in population}
    other = {'fuera_de_la_comunidad': 0, 'sin_municipio': 0, 'sin_equivalencia': 0, 'total_registros': 0}
    for row in reader:
        other['total_registros'] += 1
        kind = KINDS.get(row['establecimiento'].strip())
        if kind is None:
            continue
        province = key(row['provincia'])
        if province not in {key(p) for p, _ in PROVINCES.values()}:
            other['fuera_de_la_comunidad'] += 1
            continue
        if not row['municipio'].strip():
            other['sin_municipio'] += 1
            continue
        code = index.get((province, key(row['municipio'])))
        if code is None:
            other['sin_equivalencia'] += 1
            continue
        counts[code][kind] += 1
    return counts, other


def download():
    meta = json.loads(fetch(REGISTRY_API, JCYL))['metas']['default']
    if 'creativecommons.org/licenses/by/4.0' not in (meta.get('license_url') or ''):
        raise ValueError('Licencia del registro cambiada: revisión humana necesaria')
    raw = fetch(REGISTRY_CSV, JCYL)
    tables = {code: json.loads(fetch(f'https://{INE}/wstempus/js/ES/DATOS_TABLA/{table}?nult=1&tip=AM', INE))
              for code, (_, table) in PROVINCES.items()}
    population = parse_population(tables)
    counts, other = parse_registry(raw, population)
    if other['sin_equivalencia'] > 20:
        raise ValueError(f'{other["sin_equivalencia"]} registros sin municipio equivalente en el INE: revisa ALIASES')
    data = {'registry': {'dataset': REGISTRY_PAGE, 'modified': meta.get('modified'), 'records': meta.get('records_count'),
                         'downloaded': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                         'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'license': 'CC BY 4.0', **other},
            'population': {'source': INE_PAGE, 'year': POPULATION_YEAR, 'date': f'{POPULATION_YEAR}-01-01'},
            'municipios': {code: {**population[code], **counts[code]} for code in population}}
    atomic_write(DATA, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    return data


def load(path=DATA):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if len(data['municipios']) != MUNICIPALITIES or data['population']['year'] != POPULATION_YEAR:
        raise ValueError('Datos de Castilla y León incompletos')
    for code, m in data['municipios'].items():
        if not re.fullmatch(r'\d{5}', code) or m['habitantes'] < 0 or any(m[k] < 0 for k in KINDS.values()):
            raise ValueError(f'Municipio inválido: {code}')
    return data


def total(m):
    return sum(m[k] for k in KINDS.values())


def date_es(iso):
    months = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    return f'{int(iso[8:10])} de {months[int(iso[5:7]) - 1]} de {iso[:4]}'


def bars(items, label_id, title, desc):
    label_x, bar_x, bar_w, row_h, bar_h, top, r = 108, 112, 170, 22, 14, 10, 4
    height = top + row_h * len(items) + 6
    scale = bar_w / (max((v for _, v, _ in items), default=1) or 1)
    parts = [f'<svg class="bars" viewBox="0 0 340 {height}" role="img" aria-labelledby="{label_id}-t {label_id}-d">'
             f'<title id="{label_id}-t">{escape(title)}</title><desc id="{label_id}-d">{escape(desc)}</desc>']
    for index, (label, value, text) in enumerate(items):
        y = top + index * row_h
        width = max(value * scale, 2 * r)
        path = f'M{bar_x},{y} h{width - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} a{r},{r} 0 0 1 -{r},{r} h-{width - r:.1f} z'
        parts.append(f'<g><title>{escape(label)}: {escape(text)}</title><text class="bar-label" x="{label_x}" y="{y + 11}">{escape(label)}</text>'
                     f'<path class="bar" d="{path}"/><text class="bar-value" x="{bar_x + width + 4:.1f}" y="{y + 11}">{escape(text)}</text></g>')
    return ''.join(parts) + '</svg>'


def render(data):
    munis = data['municipios']
    reg = data['registry']
    when = date_es(reg['downloaded'])
    totals = {k: sum(m[k] for m in munis.values()) for k in KINDS.values()}
    people = sum(m['habitantes'] for m in munis.values())
    without = {c: m for c, m in munis.items() if total(m) == 0}
    nobar = {c: m for c, m in munis.items() if m['bares'] == 0}
    prov_rows, chart = [], []
    for province, _ in PROVINCES.values():
        ms = [m for m in munis.values() if m['provincia'] == province]
        w = [m for m in ms if total(m) == 0]
        est = sum(total(m) for m in ms)
        pop = sum(m['habitantes'] for m in ms)
        share = 100 * len(w) / len(ms)
        chart.append((province, share, f'{es_number(share, 0)} %'))
        prov_rows.append(f'<tr><th scope="row">{province}</th><td>{es_int(len(ms))}</td><td>{es_int(est)}</td>'
                         f'<td>{es_number(1000 * est / pop, 1)}</td><td>{es_int(len(w))}</td><td>{es_number(share, 0)} %</td>'
                         f'<td>{es_int(sum(m["habitantes"] for m in w))}</td></tr>')
    chart.sort(key=lambda x: -x[1])
    prov_foot = (f'<tfoot><tr><th scope="row">Castilla y León</th><td>{es_int(len(munis))}</td><td>{es_int(sum(totals.values()))}</td>'
                 f'<td>{es_number(1000 * sum(totals.values()) / people, 1)}</td><td>{es_int(len(without))}</td>'
                 f'<td>{es_number(100 * len(without) / len(munis), 0)} %</td><td>{es_int(sum(m["habitantes"] for m in without.values()))}</td></tr></tfoot>')
    band_rows = []
    for low, high, label in BANDS:
        ms = [m for m in munis.values() if low <= m['habitantes'] <= high]
        w = sum(1 for m in ms if total(m) == 0)
        band_rows.append(f'<tr><th scope="row">{label}</th><td>{es_int(len(ms))}</td><td>{es_int(w)}</td>'
                         f'<td>{es_number(100 * w / len(ms), 0) if ms else "—"} %</td></tr>')
    biggest = sorted(without.items(), key=lambda kv: (-kv[1]['habitantes'], kv[0]))[:25]
    big_rows = ''.join(f'<tr><th scope="row">{escape(m["nombre"])}</th><td>{escape(m["provincia"])}</td><td>{es_int(m["habitantes"])}</td></tr>'
                       for _, m in biggest)
    small = sum(1 for m in munis.values() if m['habitantes'] < 100)
    obs = [f'{es_int(len(without))} de los {es_int(len(munis))} municipios ({es_number(100 * len(without) / len(munis), 0)} %) no tienen ningún bar, '
           f'restaurante ni cafetería inscrito en el Registro de Turismo. En ellos viven {es_int(sum(m["habitantes"] for m in without.values()))} personas '
           f'({es_number(100 * sum(m["habitantes"] for m in without.values()) / people, 1)} % de la población).',
           f'{es_int(len(nobar))} municipios no tienen ningún bar registrado, aunque algunos tengan restaurante o cafetería.',
           f'{es_int(small)} municipios tienen menos de 100 habitantes.',
           f'El municipio más poblado sin ningún establecimiento de hostelería registrado es {biggest[0][1]["nombre"]} ({biggest[0][1]["provincia"]}), '
           f'con {es_int(biggest[0][1]["habitantes"])} habitantes.' if biggest else '']
    title = 'Bares, restaurantes y cafeterías en Castilla y León: municipios sin hostelería registrada | Pulso Castilla y León'
    description = (f'{es_int(totals["bares"])} bares, {es_int(totals["restaurantes"])} restaurantes y {es_int(totals["cafeterias"])} cafeterías registrados en Castilla y León, '
                   f'por provincia y municipio, y {es_int(len(without))} municipios sin ninguno. Datos abiertos de la Junta y padrón del INE.')
    dataset = {'@context': 'https://schema.org', '@type': 'Dataset', 'name': 'Hostelería registrada por municipio en Castilla y León',
               'description': description, 'url': ORIGIN, 'license': LICENSE_DEED, 'isBasedOn': [REGISTRY_PAGE, INE_PAGE],
               'spatialCoverage': 'Castilla y León', 'dateModified': reg['downloaded'],
               'creator': {'@type': 'Organization', 'name': 'Pulso Local', 'url': 'https://paniset.github.io/'},
               'distribution': {'@type': 'DataDownload', 'encodingFormat': 'text/csv', 'contentUrl': ORIGIN + CSV_NAME}}
    lost = reg['sin_municipio'] + reg['sin_equivalencia'] + reg['fuera_de_la_comunidad']
    lost_text = ('Todas las inscripciones de esos tipos se han podido asignar a un municipio.' if not lost else
                 f'{es_int(lost)} inscripciones no se asignan: {es_int(reg["sin_municipio"])} sin municipio en origen, '
                 f'{es_int(reg["fuera_de_la_comunidad"])} de fuera de la comunidad y {es_int(reg["sin_equivalencia"])} sin equivalencia en el INE.')
    page = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="style.css"><link rel="icon" href="data:,">
<script type="application/ld+json">{ld_json(dataset)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="../">Herramientas gratuitas</a> / Pulso Castilla y León</p></nav>
<h1>Bares, restaurantes y cafeterías en Castilla y León</h1>
<p class="lead">{es_int(totals["bares"])} bares, {es_int(totals["restaurantes"])} restaurantes y {es_int(totals["cafeterias"])} cafeterías inscritos en el Registro de Turismo · {es_int(len(without))} municipios sin ninguno · datos del {escape(when)}</p></header>
<p class="notice">Cuenta establecimientos inscritos en el Registro de Turismo de la Junta, no locales abiertos: puede haber inscripciones de negocios ya cerrados y bares que no figuran, como teleclubes o bares de asociaciones. El registro se agrupa por municipio, no por pueblo o núcleo.</p>
<h2>Qué se observa</h2>{''.join(f'<p>{escape(t)}</p>' for t in obs if t)}
<h2>Municipios sin hostelería registrada, por provincia</h2>
{bars(chart, 'sin', 'Porcentaje de municipios sin ningún bar, restaurante ni cafetería registrados, por provincia', 'La tabla siguiente tiene todos los valores.')}
<div class="table-wrap"><table><caption>Municipios, establecimientos de hostelería registrados y municipios sin ninguno, por provincia</caption>
<thead><tr><th scope="col">Provincia</th><th scope="col">Municipios</th><th scope="col">Bares, restaurantes y cafeterías</th><th scope="col">Por 1.000 hab.</th><th scope="col">Municipios sin ninguno</th><th scope="col">%</th><th scope="col">Habitantes en ellos</th></tr></thead>
<tbody>{''.join(prov_rows)}</tbody>{prov_foot}</table></div>
<h2>Según el tamaño del municipio</h2>
<div class="table-wrap"><table><caption>Municipios sin hostelería registrada según su población a 1 de enero de {POPULATION_YEAR}</caption>
<thead><tr><th scope="col">Habitantes</th><th scope="col">Municipios</th><th scope="col">Sin hostelería registrada</th><th scope="col">%</th></tr></thead>
<tbody>{''.join(band_rows)}</tbody></table></div>
<h2>Los municipios más poblados sin ningún establecimiento registrado</h2>
<div class="table-wrap"><table><caption>Los 25 municipios con más habitantes sin bares, restaurantes ni cafeterías en el Registro de Turismo</caption>
<thead><tr><th scope="col">Municipio</th><th scope="col">Provincia</th><th scope="col">Habitantes</th></tr></thead><tbody>{big_rows}</tbody></table></div>
<p>La lista completa de los {es_int(len(munis))} municipios, con bares, restaurantes, cafeterías y habitantes, está en el <a href="{CSV_NAME}">CSV descargable</a>.</p>
<h2>Cómo leer estos datos</h2>
<p>Se cuentan las inscripciones de tipo «Bares», «Restaurantes» y «Cafeterías» del Registro de Turismo de Castilla y León, descargado el {escape(when)}, y se asignan al municipio con la población oficial del INE a 1 de enero de {POPULATION_YEAR}. {lost_text}</p>
<p>Que un municipio no tenga inscripciones no significa que no haya ningún sitio donde tomar algo: puede haber bares sin inscribir, servicios de temporada o locales en otro pueblo cercano. Tampoco una inscripción prueba que el local siga abierto.</p>
<h2>Procedencia y licencia</h2><p>Junta de Castilla y León, <a href="{REGISTRY_PAGE}">Registro de Turismo de Castilla y León</a>, licencia <a href="{LICENSE_DEED}">CC BY 4.0</a> (solo se usan las columnas de tipo, provincia y municipio; huella {reg["sha256"][:12]}…). Población: <a href="{INE_PAGE}">INE, Padrón municipal, cifras oficiales a 1 de enero de {POPULATION_YEAR}</a>. Elaboración: Pulso Local.</p>
<footer><p><a href="../">Todas las herramientas</a> · <a href="../pulso-valencia/reutilizar-datos">Cómo reutilizar los datos</a> · <a href="{REPO}">Código abierto (MIT) en GitHub</a></p></footer></main></body></html>'''
    return protect_html(page_metadata(page, canonical=ORIGIN, social=True))


def render_csv(data):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['codigo_ine', 'municipio', 'provincia', 'habitantes', 'bares', 'restaurantes', 'cafeterias',
                     'fecha_registro', 'anio_padron', 'licencia'])
    for code, m in data['municipios'].items():
        writer.writerow([csv_safe(v) for v in (code, m['nombre'], m['provincia'], m['habitantes'], m['bares'], m['restaurantes'],
                                               m['cafeterias'], data['registry']['downloaded'], data['population']['year'], 'CC BY 4.0')])
    return '﻿' + stream.getvalue()


def build(data=None):
    data = data or load()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'index.html').write_text(render(data), encoding='utf-8')
    (OUT / CSV_NAME).write_text(render_csv(data), encoding='utf-8', newline='')
    (OUT / 'style.css').write_text(CSS, encoding='utf-8')
    import pulso_valencia
    pulso_valencia.build()  # la guía de reutilización lista también este CSV
    return sorted(p.name for p in OUT.iterdir())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--descargar', action='store_true')
    args = parser.parse_args()
    print(build(download() if args.descargar else None))


if __name__ == '__main__':
    main()
