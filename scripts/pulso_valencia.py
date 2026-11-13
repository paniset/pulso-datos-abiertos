"""Pulso València: recibos de la tasa de terrazas (mesas y sillas) por distrito y barrio. Biblioteca estándar.

Fuente: Ajuntament de València, conjunto «Recibos mesas y sillas 2020 - 2025» (CC BY 4.0) del portal
opendata.vlci.valencia.es. El CSV queda fijado por recurso, tamaño y SHA-256; solo se guardan agregados.
Por barrio se publican recibos y, solo con 5 o más recibos, su importe; el reparto por tipo de titular
(persona física, jurídica, sin personalidad) solo por distrito, para no señalar a nadie en barrios con pocos recibos.

    python scripts/pulso_valencia.py --descargar   # descarga, valida y guarda data/valencia-recibos-terrazas.json
    python scripts/pulso_valencia.py               # genera sites/paniset-github-io/site/pulso-valencia/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from factory.indexing import page_metadata  # noqa: E402
from factory.security import protect_html  # noqa: E402
from madrid import atomic_write  # noqa: E402
from pulso_sample import CSS, csv_safe, escape, es_int, es_number, ld_json, signed  # noqa: E402

HOST = 'opendata.vlci.valencia.es'
DATASET = 'https://opendata.vlci.valencia.es/dataset/recibos-mesas-y-sillas-2020-2025'
URL = ('https://opendata.vlci.valencia.es/dataset/33f175fc-b444-41d0-9111-9ccebc4e4cf7/resource/'
       'a2656f3e-c9a3-4d4c-a1a4-7ee300e33999/download/recibos-mesas-y-sillas-2020-2025.csv')
RAW_SHA256 = 'e6a654a9cddc310a38a506f680db6c8bf2fc85fe23131fc9417f9a08f51dcdd2'
RAW_BYTES = 1354516
DATA = ROOT / 'data' / 'valencia-recibos-terrazas.json'
OUT = ROOT / 'sites' / 'paniset-github-io' / 'site' / 'pulso-valencia'
ORIGIN = 'https://paniset.github.io/pulso-valencia/'
CSV_NAME = 'recibos-terrazas-valencia.csv'
LICENSE_DEED = 'https://creativecommons.org/licenses/by/4.0/deed.es'
FIELDS = {'Periodo', 'Distrito', 'Barrio', 'Codigo Distrito', 'Codigo Barrio', 'Numero Recibos personalidad fisica',
          'Numero Recibos personalidad juridica', 'Numero Recibos sin personalidad', 'Numero Recibos totales',
          'Importe recibos totales'}
MINOR = {'de', 'del', 'la', 'el', 'les', 'els', 'al', 'i', 'y'}


MIN_AMOUNT_RECEIPTS = 5  # por debajo, el importe de un barrio se acerca al de un solo titular


def check_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != HOST or parsed.username or parsed.password:
        raise ValueError('Solo recursos HTTPS de opendata.vlci.valencia.es')


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # se rechaza antes de abrir el destino redirigido
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    check_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'WebFactory-Validation/1.0'})
    with urllib.request.build_opener(OfficialRedirect()).open(request, timeout=60) as response:
        if urllib.parse.urlparse(response.url).hostname != HOST:
            raise ValueError('Redirección fuera del portal municipal')
        return response.read(10_000_001)


def integer(value):
    text = (value or '').strip()
    if not text.isdecimal():
        raise ValueError(f'Número de recibos inválido: {value!r}')
    return int(text)


def amount(value):
    result = float((value or '').strip())
    if not 0 <= result < 1e9:
        raise ValueError(f'Importe inválido: {value!r}')
    return result


def parse(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';')
    if not FIELDS <= set(reader.fieldnames or []):
        raise ValueError('Esquema del CSV de recibos incompatible')
    years = {}
    for line, row in enumerate(reader, 2):
        year = row['Periodo'].strip()
        if not (year.isdecimal() and len(year) == 4):
            raise ValueError(f'Periodo inválido en la fila {line}')
        district = ' '.join(row['Distrito'].split()).upper()
        barrio = ' '.join(row['Barrio'].split()).upper()
        if not district or not barrio:
            raise ValueError(f'Distrito o barrio vacío en la fila {line}')
        fisica, juridica, sin = (integer(row[f'Numero Recibos {k}']) for k in
                                 ('personalidad fisica', 'personalidad juridica', 'sin personalidad'))
        total = integer(row['Numero Recibos totales'])
        key = f'{district}|{barrio}'
        year_data = years.setdefault(year, {'barrios': {}, 'districts': {}, 'mismatch': 0})
        if fisica + juridica + sin != total:
            # En origen hay filas cuyo desglose por titular no suma el total: manda el total.
            year_data['mismatch'] += 1
            year_data['mismatch_max'] = max(year_data.get('mismatch_max', 0), abs(fisica + juridica + sin - total))
        if key in year_data['barrios']:
            raise ValueError(f'Barrio repetido en {year}: {key}')
        year_data['barrios'][key] = {'recibos': total, 'importe': round(amount(row['Importe recibos totales']), 2)}
        d = year_data['districts'].setdefault(district, {'recibos': 0, 'fisica': 0, 'juridica': 0, 'sin': 0, 'importe': 0.0})
        d['recibos'] += total; d['fisica'] += fisica; d['juridica'] += juridica; d['sin'] += sin
        d['importe'] += amount(row['Importe recibos totales'])
    all_districts = set().union(*(set(y['districts']) for y in years.values()))
    result = {}
    for year, data in sorted(years.items()):
        for d in data['districts'].values():
            d['importe'] = round(d['importe'], 2)
        result[year] = {'complete': set(data['districts']) == all_districts, 'mismatch': data['mismatch'],
                        'mismatch_max': data.get('mismatch_max', 0),
                        'districts': dict(sorted(data['districts'].items())),
                        'barrios': dict(sorted(data['barrios'].items()))}
    return result


def download():
    raw = fetch(URL)
    if len(raw) != RAW_BYTES or hashlib.sha256(raw).hexdigest() != RAW_SHA256:
        raise ValueError('El CSV de recibos ha cambiado: revisa los datos y actualiza el hash fijado')
    data = {'source': {'dataset': DATASET, 'url': URL, 'sha256': RAW_SHA256, 'bytes': RAW_BYTES, 'license': 'CC BY 4.0'},
            'years': parse(raw)}
    atomic_write(DATA, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    return data


def load(path=DATA):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['source'] != {'dataset': DATASET, 'url': URL, 'sha256': RAW_SHA256, 'bytes': RAW_BYTES, 'license': 'CC BY 4.0'}:
        raise ValueError('Procedencia distinta de la fijada')
    for year, value in data['years'].items():
        for name, d in value['districts'].items():
            if sum(b['recibos'] for k, b in value['barrios'].items() if k.split('|')[0] == name) != d['recibos']:
                raise ValueError(f'{year} {name}: barrios no suman el distrito')
    return data


# Nombres que en origen vienen en mayúsculas sin tildes.
ACCENTS = {'ALGIROS': 'Algirós', 'JESUS': 'Jesús', 'POBLATS MARITIMS': 'Poblats Marítims', 'LA SAIDIA': 'La Saïdia',
           'CIUTAT JARDI': 'Ciutat Jardí'}


def nice(name):
    if name in ACCENTS:
        return ACCENTS[name]
    words = name.lower().split(' ')
    out = []
    for index, word in enumerate(words):
        if index and word in MINOR:
            out.append(word)
        elif "'" in word:
            head, tail = word.split("'", 1)
            out.append(head.capitalize() + "'" + tail.capitalize() if index == 0 else head + "'" + tail.capitalize())
        else:
            out.append('-'.join(part.capitalize() for part in word.split('-')))
    return ' '.join(out)


def share(d):
    """Porcentaje de recibos de personas jurídicas sobre el desglose por titular (no sobre el total)."""
    breakdown = d['fisica'] + d['juridica'] + d['sin']
    return es_number(100 * d['juridica'] / breakdown, 0) if breakdown else '—'


def barrio_amount(entry):
    if not entry:
        return '0 €'
    return euros(entry['importe']) if entry['recibos'] >= MIN_AMOUNT_RECEIPTS else '—'


def euros(value):
    return es_int(round(value)) + ' €'


def bars(items, label_id, title, desc):
    label_x, bar_x, bar_w, row_h, bar_h, top, r = 128, 132, 150, 22, 14, 10, 4
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
    years = data['years']
    complete = [y for y, v in years.items() if v['complete']]
    partial = [y for y, v in years.items() if not v['complete']]
    if len(complete) < 2:
        raise ValueError('Hacen falta al menos dos años completos para comparar')
    last, prev, first = complete[-1], complete[-2], complete[0]
    L, P, F = years[last], years[prev], years[first]
    tot = lambda y: sum(d['recibos'] for d in years[y]['districts'].values())
    imp = lambda y: sum(d['importe'] for d in years[y]['districts'].values())
    districts = sorted(L['districts'], key=lambda n: (-L['districts'][n]['recibos'], n))
    chart_years = bars([(y, tot(y), es_int(tot(y))) for y in complete], 'anios', 'Recibos de la tasa de terrazas por año',
                       f'De {es_int(tot(first))} en {first} a {es_int(tot(last))} en {last}. Solo años completos.')
    chart_districts = bars([(nice(n), L['districts'][n]['recibos'], es_int(L['districts'][n]['recibos'])) for n in districts],
                           'dist', f'Recibos de la tasa de terrazas por distrito en {last}',
                           f'De {nice(districts[0])} ({es_int(L["districts"][districts[0]]["recibos"])}) a {nice(districts[-1])} '
                           f'({es_int(L["districts"][districts[-1]]["recibos"])}). La tabla siguiente tiene todos los valores.')
    d_rows = ''.join(
        f'<tr><th scope="row">{escape(nice(n))}</th>' + ''.join(f'<td>{es_int(years[y]["districts"].get(n, {}).get("recibos", 0))}</td>' for y in complete)
        + f'<td>{signed(L["districts"][n]["recibos"] - P["districts"].get(n, {}).get("recibos", 0))}</td>'
        f'<td>{euros(L["districts"][n]["importe"])}</td><td>{share(L["districts"][n])} %</td></tr>'
        for n in districts)
    d_foot = (f'<tfoot><tr><th scope="row">València</th>' + ''.join(f'<td>{es_int(tot(y))}</td>' for y in complete)
              + f'<td>{signed(tot(last) - tot(prev))}</td><td>{euros(imp(last))}</td>'
              f'<td>{share({k: sum(d[k] for d in L["districts"].values()) for k in ("fisica", "juridica", "sin")})} %</td></tr></tfoot>')
    barrio_keys = sorted(set(L['barrios']) | set(P['barrios']), key=lambda k: (k.split('|')[0], k.split('|')[1]))
    b_rows = ''.join(
        f'<tr><th scope="row">{escape(nice(k.split("|")[1]))}</th><td>{escape(nice(k.split("|")[0]))}</td>'
        f'<td>{es_int(P["barrios"].get(k, {}).get("recibos", 0))}</td><td>{es_int(L["barrios"].get(k, {}).get("recibos", 0))}</td>'
        f'<td>{signed(L["barrios"].get(k, {}).get("recibos", 0) - P["barrios"].get(k, {}).get("recibos", 0))}</td>'
        f'<td>{barrio_amount(L["barrios"].get(k))}</td></tr>' for k in barrio_keys)
    top_b = sorted(L['barrios'].items(), key=lambda kv: (-kv[1]['recibos'], kv[0]))[:10]
    change = {k: L['barrios'].get(k, {}).get('recibos', 0) - P['barrios'].get(k, {}).get('recibos', 0) for k in barrio_keys}
    up = max(barrio_keys, key=lambda k: (change[k], k)); down = min(barrio_keys, key=lambda k: (change[k], k))
    obs = [f'En {last} el Ayuntamiento emitió {es_int(tot(last))} recibos de la tasa de mesas y sillas por {euros(imp(last))} '
           f'({euros(imp(last) / tot(last))} de media por recibo).',
           f'Respecto a {prev}: {signed(tot(last) - tot(prev))} recibos ({signed(100 * (tot(last) - tot(prev)) / tot(prev), 1)} %). '
           f'Respecto a {first}: {signed(tot(last) - tot(first))}.',
           f'{nice(districts[0])} concentra {es_int(L["districts"][districts[0]]["recibos"])} recibos, '
           f'el {es_number(100 * L["districts"][districts[0]]["recibos"] / tot(last), 0)} % de la ciudad.',
           f'Los diez barrios con más recibos suman el {es_number(100 * sum(v["recibos"] for _, v in top_b) / tot(last), 0)} % del total.']
    if change[up] > 0:
        obs.append(f'El barrio que más sube frente a {prev} es {nice(up.split("|")[1])} ({signed(change[up])}).')
    if change[down] < 0:
        obs.append(f'El que más baja es {nice(down.split("|")[1])} ({signed(change[down])}).')
    title = f'Terrazas en València por barrio y distrito: recibos de la tasa {first}-{last} | Pulso València'
    description = (f'Recibos de la tasa de mesas y sillas (terrazas) en València por distrito y barrio: {es_int(tot(last))} en {last}, '
                   f'{euros(imp(last))}, y su evolución desde {first}. Datos abiertos del Ajuntament de València.')
    dataset = {'@context': 'https://schema.org', '@type': 'Dataset', 'name': f'Recibos de la tasa de terrazas en València por barrio ({first}-{last})',
               'description': description, 'url': ORIGIN, 'license': LICENSE_DEED, 'isBasedOn': DATASET,
               'temporalCoverage': f'{first}/{last}', 'spatialCoverage': 'València',
               'creator': {'@type': 'Organization', 'name': 'Pulso Local', 'url': 'https://paniset.github.io/'},
               'distribution': {'@type': 'DataDownload', 'encodingFormat': 'text/csv', 'contentUrl': ORIGIN + CSV_NAME}}
    bad = {y: v['mismatch'] for y, v in years.items() if v.get('mismatch')}
    worst = max((v.get('mismatch_max', 0) for v in years.values()), default=0)
    units = '1 unidad' if worst == 1 else f'{worst} unidades'
    mismatch_note = (f'<p>En el conjunto original, {"; ".join(f"{n} filas de {y}" for y, n in bad.items())} tienen un desglose por titular que no suma '
                     f'el total de recibos (difiere como mucho en {units}): se usa el total, y el porcentaje de personas jurídicas se calcula sobre el desglose.</p>') if bad else ''
    covid = (' Según el Ajuntament, el conjunto no incluye 2021 porque ese año no se concedieron matrículas por la pandemia.'
             if '2021' not in years and first < '2021' < last else '')
    head_years = ''.join(f'<th scope="col">{y}</th>' for y in complete)
    page = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="style.css"><link rel="icon" href="data:,">
<script type="application/ld+json">{ld_json(dataset)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="../">Herramientas gratuitas</a> / Pulso València</p></nav>
<h1>Terrazas en València por barrio y distrito</h1>
<p class="lead">Recibos de la tasa de mesas y sillas · {es_int(tot(last))} en {last} · {euros(imp(last))}</p></header>
<p class="notice">Cuenta recibos de la tasa municipal por ocupación de la vía pública con mesas y sillas, no terrazas en funcionamiento: un establecimiento puede tener más de un recibo y un recibo no prueba que la terraza se monte todo el año.</p>
<h2>Recibos por año</h2>{chart_years}
<p class="small">Años completos: {", ".join(complete)}.{covid}{f" El año {', '.join(partial)} aparece en el conjunto con solo una parte de los distritos y no se compara." if partial else ""}</p>
<h2>Qué se observa</h2>{''.join(f'<p>{escape(t)}</p>' for t in obs)}
<h2>Por distrito en {last}</h2>{chart_districts}
<div class="table-wrap"><table><caption>Recibos de la tasa de terrazas por distrito y año, variación {prev}-{last}, importe y porcentaje de titulares que son personas jurídicas en {last}</caption>
<thead><tr><th scope="col">Distrito</th>{head_years}<th scope="col">Variación</th><th scope="col">Importe {last}</th><th scope="col">Personas jurídicas</th></tr></thead>
<tbody>{d_rows}</tbody>{d_foot}</table></div>
<h2>Barrios con más recibos en {last}</h2><ol>{''.join(f'<li>{escape(nice(k.split("|")[1]))} ({escape(nice(k.split("|")[0]))}): {es_int(v["recibos"])}</li>' for k, v in top_b)}</ol>
<h2>Todos los barrios</h2>
<div class="table-wrap"><table><caption>Recibos por barrio en {prev} y {last}, variación e importe en {last}, ordenados por distrito</caption>
<thead><tr><th scope="col">Barrio</th><th scope="col">Distrito</th><th scope="col">{prev}</th><th scope="col">{last}</th><th scope="col">Variación</th><th scope="col">Importe {last}</th></tr></thead>
<tbody>{b_rows}</tbody></table></div>
<h2>Cómo leer estos datos</h2>
<p>Cada fila del conjunto municipal da, por barrio y año, el número de recibos emitidos de la tasa por mesas y sillas y su importe. El importe es lo facturado en recibos, no lo cobrado. El reparto por tipo de titular (persona física, jurídica o sin personalidad) se muestra solo por distrito.</p>
{mismatch_note}<p>En barrios con menos de {MIN_AMOUNT_RECEIPTS} recibos no se muestra el importe (—), porque se acercaría al de un solo titular.</p><p>Un barrio que no aparece en un año se cuenta con 0 recibos. La variación entre años puede deberse a altas y bajas de licencias, a cambios en la tasa o a correcciones administrativas. Esta página no interpreta la ordenanza municipal.</p>
<p><a href="{CSV_NAME}">Descargar los datos por barrio y año en CSV</a> · <a href="https://paniset.github.io/pulso-local-madrid/">Pulso Local Madrid: el registro de terrazas de Madrid</a></p>
<h2>Procedencia y licencia</h2><p>Ajuntament de València, <a href="{DATASET}">Recibos mesas y sillas 2020 - 2025</a>, portal de datos abiertos, licencia <a href="{LICENSE_DEED}">CC BY 4.0</a>. Fichero fijado por su huella SHA-256 ({RAW_SHA256[:12]}…). Solo se publican agregados.</p>
<footer><p><a href="../">Todas las herramientas</a> · <a href="../acerca">Acerca de</a> · <a href="https://github.com/paniset/pulso-datos-abiertos">Código abierto (MIT) en GitHub</a></p></footer></main></body></html>'''
    page = page_metadata(page, canonical=ORIGIN, social=True)
    return protect_html(page)


def render_csv(data):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['anio', 'distrito', 'barrio', 'recibos', 'importe_eur', 'anio_completo', 'fuente', 'licencia'])
    for year, value in data['years'].items():
        for key, b in value['barrios'].items():
            district, barrio = key.split('|')
            amount_text = f'{b["importe"]:.2f}'.replace('.', ',') if b['recibos'] >= MIN_AMOUNT_RECEIPTS else ''
            writer.writerow([csv_safe(v) for v in (year, nice(district), nice(barrio), b['recibos'], amount_text,
                                                   'sí' if value['complete'] else 'no', DATASET, 'CC BY 4.0')])
    return '﻿' + stream.getvalue()


def build(data=None):
    data = data or load()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'index.html').write_text(render(data), encoding='utf-8')
    (OUT / CSV_NAME).write_text(render_csv(data), encoding='utf-8', newline='')
    (OUT / 'style.css').write_text(CSS, encoding='utf-8')
    return sorted(p.name for p in OUT.iterdir())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--descargar', action='store_true')
    args = parser.parse_args()
    data = download() if args.descargar else None
    print(build(data))


if __name__ == '__main__':
    main()
