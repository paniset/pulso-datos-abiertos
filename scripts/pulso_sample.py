"""Muestra gratuita reproducible a partir del radar saneado, sin red."""
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factory.radar_schema import validate_radar
from factory.indexing import APPROVED

LABELS = {'entrada': 'Presente solo en el corte final',
          'salida': 'Ausente en el corte final',
          'cambio_estado': 'Cambio de estado, periodo o zona',
          'cambio_actividad': 'Cambio de actividad'}
FIELDS = ['id', 'local_id', 'district', 'neighborhood', 'activity', 'type', 'before', 'after', 'changed_fields']
CSS = '\n*{box-sizing:border-box}body{font-family:Arial,sans-serif;color:#17333f;margin:0;background:#edf3f5;line-height:1.5}main{max-width:1050px;margin:auto;background:white;padding:44px}h1{font-size:38px;line-height:1.15}h2{margin-top:36px}h3{font-size:17px}h3 span{font-weight:normal}a{color:#17566f;overflow-wrap:anywhere}.lead{font-size:20px}.notice{border-left:5px solid #b47b20;padding:14px;background:#fff5df}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;border-bottom:1px solid #b9cbd2;text-align:left}thead{background:#e5eff2}.record{border-top:2px solid #8daab5;padding:12px 0;break-inside:avoid}dl{display:grid;grid-template-columns:110px 1fr;gap:8px}dt{font-weight:bold}dd{margin:0}.small{font-size:13px}.hash{font-size:12px;overflow-wrap:anywhere}.table-wrap{overflow-x:auto}@media(max-width:600px){main{padding:20px}h1{font-size:30px}dl{display:block}dd{margin-bottom:12px}}.bars{display:block;width:100%;max-width:620px;height:auto;margin:16px 0}.bars text{font-family:Arial,sans-serif;font-size:11px;fill:#17333f}.bars .bar-label{text-anchor:end}.bars .bar-value,.bars .avg-label{paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}.bars .bar{fill:#164c63}.bars .avg-line{stroke:#6b7f88;stroke-width:1;stroke-dasharray:3 3}.bars .avg-label{font-size:10px;fill:#4d6670;text-anchor:middle}.line-chart{display:block;width:100%;max-width:620px;height:auto;margin:16px 0}.line-chart text{font-family:Arial,sans-serif;font-size:10px;fill:#4d6670}.line-chart .axis{text-anchor:end}.line-chart .axis-x{text-anchor:middle}.line-chart .start{text-anchor:start}.line-chart .end{text-anchor:end}.line-chart .grid{stroke:#d6e2e7;stroke-width:1}.line-chart .series{fill:none;stroke:#164c63;stroke-width:2;stroke-linejoin:round}.line-chart .point{fill:#164c63;stroke:#fff;stroke-width:2}@page{size:A4;margin:17mm}@media print{body,main{background:white;margin:0;padding:0}body{font-size:10pt}h1{font-size:26pt}h2,h3{break-after:avoid}thead{display:table-header-group}tr{break-inside:avoid}.table-wrap{overflow:visible}.screen{display:none}a{color:inherit}}\n'

NOTE = 'Diferencia administrativa; no apertura o cierre confirmado.'

def escape(value):
    return html.escape('No consta en este corte' if value is None else str(value), quote=True)

def csv_safe(value):
    text = '' if value is None else str(value)
    # Neutraliza fórmulas también tras espacios y controles iniciales.
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        text = "'" + text
    return text

def render_csv(data, digest):
    meta = data['meta']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(FIELDS + ['from_date', 'to_date', 'source_url', 'license', 'attribution', 'radar_sha256', 'interpretation', 'mode'])
    for item in data['changes']:
        values = [', '.join(item[key]) if key == 'changed_fields' else item.get(key) for key in FIELDS]
        values += [meta['from_date'], meta['to_date'], meta['source_url'], meta.get('license', 'No indicada'), meta.get('attribution', 'Datos sintéticos de demostración'), digest, NOTE, meta['mode']]
        writer.writerow([csv_safe(value) for value in values])
    return '\ufeff' + stream.getvalue()

def render_html(data, digest):
    meta, changes = data['meta'], data['changes']
    counts = Counter(item['type'] for item in changes)
    districts = sorted({item['district'] for item in changes})
    summary = ''.join('<tr><th scope="row">' + escape(district) + '</th>' + ''.join(
        f'<td>{sum(item["district"] == district and item["type"] == kind for item in changes)}</td>' for kind in LABELS if kind in counts
    ) + f'<td>{sum(item["district"] == district for item in changes)}</td></tr>' for district in districts)
    records = []
    for item in changes:
        records.append(f'''<article class="record" id="terraza-{escape(item['id'])}">
<h3>Terraza {escape(item['id'])} <span>· {escape(LABELS[item['type']])}</span></h3>
<p>{escape(item['district'])} / {escape(item['neighborhood'])} · Local {escape(item['local_id'])}</p>
<p>{escape(item['activity'])}</p><dl><dt>Corte inicial</dt><dd>{escape(item['before'])}</dd>
<dt>Corte final</dt><dd>{escape(item['after'])}</dd></dl>
<p class="small">Campos modificados: {escape(', '.join(item['changed_fields']) or 'No aplica: presencia entre cortes')}.</p></article>''')
    sources = ''.join(f'''<li><a href="{escape(source['url'])}">{escape(source['description'])}</a>
<p>Recurso: {escape(source['resource_id'])}. Periodo: {escape(source['period'])}. Tamaño: {source['bytes']} bytes.</p>
<p class="hash">SHA-256: {escape(source['sha256'])}</p></li>''' for source in meta['sources'])
    license_text = (f'<a href="{escape(meta["license_url"])}">{escape(meta.get("license", "No indicada"))}</a>' if meta.get('license_url') else escape(meta.get('license', 'No indicada')))
    notes = ''.join(f'<p>{escape(meta[key])}</p>' for key in ['date_note', 'coverage_note', 'selection_note', 'privacy_note'] if key in meta)
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Terrazas de Madrid: {len(changes)} cambios en el registro del {escape(meta['from_date'])} al {escape(meta['to_date'])} | Pulso Local</title><meta name="description" content="Muestra imprimible de {len(changes)} cambios del registro municipal de terrazas de hostelería de Madrid entre dos cortes, por distrito, con fuentes, licencia y descarga CSV. Un cambio administrativo no prueba una apertura o un cierre."><link rel="stylesheet" href="muestra.css"></head><body><main><header><p><a href="./">Pulso Local</a> / Madrid</p><h1>{len(changes)} cambios en el registro de terrazas</h1>
<p class="lead">Cortes del {escape(meta['from_date'])} al {escape(meta['to_date'])}</p><p>Muestra gratuita · Sin cobros · {'DEMO: datos sintéticos, no hechos reales' if meta['mode'] == 'synthetic' else 'Datos administrativos reales'}</p></header>
<p class="notice">{NOTE} Este informe no acredita aperturas, cierres, demanda comercial ni ingresos. No se declara revisión humana de los registros.</p>
<p class="screen"><a href="pulso-muestra.csv" download>Descargar los {len(changes)} cambios en CSV</a> · Para imprimir, usa la opción Imprimir del navegador.</p>
<h2>Resumen por distrito y tipo</h2><p>{len(changes)} cambios: {escape('; '.join(f'{count} {LABELS[kind].lower()}' for kind, count in sorted(counts.items())) or 'sin registros')}. Las cifras describen esta muestra saneada, no todos los cambios del censo municipal. <a href="{DISTRICT_HREF}">Ver la tabla por distrito ordenada por número de cambios</a>.</p>
<div class="table-wrap"><table><caption>Recuento de los registros incluidos</caption><thead><tr><th scope="col">Distrito</th>{''.join('<th scope="col">'+escape(LABELS[k])+'</th>' for k in LABELS if k in counts)}<th scope="col">Total</th></tr></thead><tbody>{summary}</tbody></table></div>
<h2>Cómo interpretar esta muestra</h2>{notes}<p>Una entrada significa presencia solo en el corte final; una salida, ausencia en ese corte. Los cambios comparan los campos indicados en cada ficha. El estado «Abierto» es un valor administrativo de la fuente, no una comprobación sobre el terreno. Los identificadores permiten enlazar con la fuente pública: no se promete anonimización absoluta.</p><p><a href="{GUIDE_HREF}">Guía: cómo leer el censo de terrazas de Madrid y qué significa cada cambio</a></p>
<h2>Procedencia y licencia</h2><p>{escape(meta.get('attribution', 'Datos sintéticos de demostración'))}</p><p><a href="{escape(meta['source_url'])}">Conjunto municipal de origen</a>. Licencia {license_text}. Transformación de esta muestra: agrupación, formato HTML y CSV; sin añadir fuentes ni contactos.</p>
<p>Datos saneados generados el {escape(meta['generated_at'])}. Entrada local: data/radar.json.</p><p class="hash">SHA-256 del archivo saneado: {escape(digest)}</p><ul>{sources}</ul>
<h2>Detalle de los {len(changes)} cambios</h2>{''.join(records)}<footer><p>Fin de la muestra gratuita. Contrasta los registros con la fuente y su contexto antes de tomar decisiones.</p><p><a href="./">Volver al radar de Pulso Local</a> · <a href="{DISTRICT_HREF}">Terrazas de Madrid por distrito</a> · <a href="{GUIDE_HREF}">Cómo leer el censo de terrazas</a></p></footer></main></body></html>'''

DISTRICT_PAGE = 'terrazas-madrid-por-distrito.html'
DISTRICT_HREF = 'terrazas-madrid-por-distrito'
# Guía estática de site/: viaja con los archivos generados para que la copien el pipeline y el build.
GUIDE_PAGE = 'como-leer-censo-terrazas-madrid.html'
GUIDE_HREF = 'como-leer-censo-terrazas-madrid'
SUMMARY_MARKER = '<!--pulso:resumen-->'
# Frases para texto corrido: describen el registro, nunca aperturas o cierres.
PHRASES = {'entrada': ('aparece en el corte final', 'aparecen en el corte final'),
           'salida': ('no aparece en el corte final', 'no aparecen en el corte final'),
           'cambio_estado': ('cambia de estado, periodo o zona', 'cambian de estado, periodo o zona'),
           'cambio_actividad': ('cambia de actividad', 'cambian de actividad')}
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre']
ORGANIZATION = {'@type': 'Organization', 'name': 'Pulso Local', 'url': APPROVED[('pulso-local', 'radar')][0] + '/'}
LICENSE_DEED = 'https://creativecommons.org/licenses/by/4.0/deed.es'


def es_date(value, year=True):
    day = value[8:10] + '/' + value[5:7]
    return day + '/' + value[:4] if year else day


def period(meta):
    start, end = meta['from_date'], meta['to_date']
    return f'{es_date(start, start[:4] != end[:4])}–{es_date(end)}'


def phrase(kind, count):
    singular, plural = PHRASES.get(kind, ('cambia en el registro', 'cambian en el registro'))
    return f'{count} {"terraza" if count == 1 else "terrazas"} {singular if count == 1 else plural}'


def plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


def district_stats(changes):
    """Distritos ordenados por total descendente y nombre; desglose por tipo."""
    totals = Counter(item['district'] for item in changes)
    kinds = [kind for kind in LABELS if any(item['type'] == kind for item in changes)]
    rows = [(district, total, {kind: sum(i['district'] == district and i['type'] == kind for i in changes) for kind in kinds})
            for district, total in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))]
    return kinds, rows


def breakdown(changes):
    counts = Counter(item['type'] for item in changes)
    return '; '.join(phrase(kind, counts[kind]) for kind in LABELS if counts[kind]) or 'sin cambios publicados'


def coverage(meta, changes):
    if meta['total_changes'] == len(changes):
        return ''
    return f' Se publican {len(changes)} de las {meta["total_changes"]} diferencias detectadas; las cifras por distrito describen solo las publicadas.'


def ld_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


def render_summary(data):
    meta, changes = data['meta'], data['changes']
    _, rows = district_stats(changes)
    top = ', '.join(f'{escape(district)} ({total})' for district, total, _ in rows[:3])
    top_text = f'<p>Distritos con más cambios: {top}.</p>' if rows else ''
    demo = '<p class="small">DEMO: datos sintéticos, no hechos reales.</p>' if meta['mode'] == 'synthetic' else ''
    density = density_rows(data)
    if density:
        top_text += (f'<p>Por habitante: {escape(display(density[0][0]))} tiene {es_number(density[0][3])} terrazas registradas por cada 10.000 habitantes empadronados '
                     f'y {escape(display(density[-1][0]))}, {es_number(density[-1][3])} (media de la ciudad: {es_number(city_rate(density))}). '
                     f'<a href="{DISTRICT_HREF}#{DENSITY_ANCHOR}">Ver el cruce con el padrón</a>'
                     + (f' · <a href="{BARRIO_HREF}">Ver los {len(data["districts"]["barrios"])} barrios</a>' if data['districts'].get('barrios') else '')
                     + (f' · <a href="{SURFACE_HREF}">Superficie y sillas</a>' if surface_rows(data) else '')
                     + '</p>')
    if data.get('series'):
        months = data['series']['months']
        change = months[-1]['total'] - months[0]['total']
        top_text += (f'<p>Evolución: {es_int(months[0]["total"])} terrazas registradas en {escape(month_name(months[0]["period"]))} y '
                     f'{es_int(months[-1]["total"])} en {escape(month_name(months[-1]["period"]))} ({signed(change)}). '
                     f'<a href="{SERIES_HREF}">Ver la evolución mes a mes</a></p>')
    return (f'<section id="resumen" class="summary" aria-labelledby="resumen-titulo"><p class="edition">Resumen de la última comparación</p>'
            f'<h2 id="resumen-titulo">{plural(len(changes), "cambio", "cambios")} en el registro de terrazas entre el {escape(es_date(meta["from_date"]))} y el {escape(es_date(meta["to_date"]))}</h2>'
            f'<p>{escape(breakdown(changes))}. Cambios repartidos en {plural(len(rows), "distrito", "distritos")}.{escape(coverage(meta, changes))}</p>{top_text}'
            '<p class="small">Comparación de dos cortes del registro municipal: un cambio no prueba que un local haya empezado o dejado de funcionar. '
            f'Fuente: Ayuntamiento de Madrid, <a href="{escape(meta["source_url"])}">conjunto de datos de origen</a>, licencia '
            f'{escape(meta.get("license", "No indicada"))}.</p>{demo}'
            f'<p><a href="{DISTRICT_HREF}">Ver la tabla por distrito</a> · <a href="muestra">Abrir el informe gratuito con los {len(changes)} registros y su CSV</a></p></section>')


def dataset_name(meta):
    start, end = meta['from_date'], meta['to_date']
    first, last = MONTHS[int(start[5:7]) - 1], MONTHS[int(end[5:7]) - 1]
    span = f'{first}-{last} {end[:4]}' if start[:4] == end[:4] else f'{first} {start[:4]}-{last} {end[:4]}'
    return f'Cambios en el registro de terrazas de hostelería de Madrid ({span})'


def render_index(page, data):
    """Inserta el resumen estático y fecha el Dataset JSON-LD con los metadatos del radar."""
    if page.count(SUMMARY_MARKER) > 1:
        raise ValueError('La portada del radar debe contener como mucho una marca <!--pulso:resumen-->')
    page = page.replace(SUMMARY_MARKER, render_summary(data))
    pattern = re.compile(r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S)
    match = pattern.search(page)
    if match:
        meta = data['meta']
        dataset = json.loads(match.group(2))
        generated = meta['generated_at'][:10]
        dataset.update(name=dataset_name(meta), temporalCoverage=f'{meta["from_date"]}/{meta["to_date"]}',
                       dateModified=generated, publisher=ORGANIZATION)
        if data.get('districts'):
            dataset['isBasedOn'] = [meta['source_url'], data['districts']['population_source']['dataset']]
        page = page[:match.start(2)] + ld_json(dataset) + page[match.end(2):]
    return page


DENSITY_CSV = 'terrazas-madrid-distritos.csv'
DENSITY_ANCHOR = 'por-habitante'
# Nombres de distrito con tildes para mostrar; la clave es la del registro municipal.
DISPLAY = {'CHAMARTIN': 'Chamartín', 'CHAMBERI': 'Chamberí', 'TETUAN': 'Tetuán', 'VICALVARO': 'Vicálvaro',
           'VILLA DE VALLECAS': 'Villa de Vallecas', 'PUENTE DE VALLECAS': 'Puente de Vallecas',
           'FUENCARRAL-EL PARDO': 'Fuencarral-El Pardo', 'SAN BLAS-CANILLEJAS': 'San Blas-Canillejas'}


def display(district):
    return DISPLAY.get(district, district.title())


def long_date(value):
    return f'{int(value[8:10])} de {MONTHS[int(value[5:7]) - 1]} de {value[:4]}'


def es_number(value, decimals=1):
    return f'{value:.{decimals}f}'.replace('.', ',')


def es_int(value):
    return f'{value:,}'.replace(',', '.')


def density_rows(data):
    """(distrito, terrazas, población, terrazas por 10.000 hab.) ordenado de mayor a menor tasa."""
    context = data.get('districts')
    if not context:
        return []
    rows = [(row['district'], row['terraces'], row['population'], 10000 * row['terraces'] / row['population'])
            for row in context['rows']]
    return sorted(rows, key=lambda row: (-row[3], row[0]))


def city_rate(rows):
    return 10000 * sum(row[1] for row in rows) / sum(row[2] for row in rows)


def density_svg(rows):
    """Barras horizontales estáticas (sin estilos en línea, compatibles con la CSP)."""
    label_x, bar_x, bar_w, row_h, bar_h, top, r = 128, 132, 168, 22, 14, 26, 4
    average = city_rate(rows)
    height = top + row_h * len(rows) + 6
    scale = bar_w / max(row[3] for row in rows)
    avg_x = bar_x + average * scale
    parts = [f'<svg class="bars" viewBox="0 0 340 {height}" role="img" aria-labelledby="bars-title bars-desc">'
             '<title id="bars-title">Terrazas registradas por cada 10.000 habitantes, por distrito</title>'
             f'<desc id="bars-desc">De {escape(display(rows[0][0]))} ({es_number(rows[0][3])}) a {escape(display(rows[-1][0]))} '
             f'({es_number(rows[-1][3])}); media de la ciudad {es_number(average)}. Los datos completos están en la tabla siguiente.</desc>',
             f'<line class="avg-line" x1="{avg_x:.1f}" x2="{avg_x:.1f}" y1="{top - 8}" y2="{height - 4}"/>',
             f'<text class="avg-label" x="{avg_x:.1f}" y="{top - 12}">Media: {es_number(average)}</text>']
    for index, (district, terraces, population, rate) in enumerate(rows):
        y = top + index * row_h
        width = max(rate * scale, 2 * r)
        path = (f'M{bar_x},{y} h{width - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} '
                f'a{r},{r} 0 0 1 -{r},{r} h-{width - r:.1f} z')
        parts.append(f'<g><title>{escape(display(district))}: {es_number(rate)} terrazas por cada 10.000 habitantes '
                     f'({es_int(terraces)} terrazas; {es_int(population)} habitantes)</title>'
                     f'<text class="bar-label" x="{label_x}" y="{y + 11}">{escape(display(district))}</text>'
                     f'<path class="bar" d="{path}"/>'
                     f'<text class="bar-value" x="{bar_x + width + 4:.1f}" y="{y + 11}">{es_number(rate)}</text></g>')
    parts.append('</svg>')
    return ''.join(parts)


def density_observations(rows):
    first, last = rows[0], rows[-1]
    average = city_rate(rows)
    above = sum(row[3] > average for row in rows)
    return [f'{display(first[0])} tiene {es_number(first[3])} terrazas registradas por cada 10.000 habitantes y '
            f'{display(last[0])}, {es_number(last[3])}: unas {es_number(first[3] / last[3], 0)} veces menos.',
            f'{plural(above, "distrito queda", "distritos quedan")} por encima de la media de la ciudad '
            f'({es_number(average)}) y {plural(len(rows) - above, "distrito", "distritos")} por debajo.',
            f'En total hay {es_int(sum(row[1] for row in rows))} registros de terraza para '
            f'{es_int(sum(row[2] for row in rows))} habitantes empadronados.']


def render_density(data):
    rows = density_rows(data)
    if not rows:
        return ''
    context = data['districts']
    source = context['population_source']
    body = ''.join(f'<tr><th scope="row">{escape(display(district))}</th><td>{es_int(terraces)}</td><td>{es_int(population)}</td>'
                   f'<td>{es_number(rate)}</td></tr>' for district, terraces, population, rate in rows)
    foot = (f'<tfoot><tr><th scope="row">Madrid</th><td>{es_int(sum(r[1] for r in rows))}</td><td>{es_int(sum(r[2] for r in rows))}</td>'
            f'<td>{es_number(city_rate(rows))}</td></tr></tfoot>')
    return (f'<h2 id="{DENSITY_ANCHOR}">Terrazas por cada 10.000 habitantes</h2>'
            f'<p>Cruce de dos conjuntos de datos abiertos del Ayuntamiento: los registros de terraza del corte del {escape(es_date(context["terraces_date"]))} '
            f'y la población empadronada a {escape(long_date(context["population_date"]))}. Indica cuántas terrazas hay registradas en relación con quienes viven en cada distrito.</p>'
            + density_svg(rows)
            + '<div class="table-wrap"><table><caption>Terrazas registradas y población por distrito, ordenadas por terrazas por cada 10.000 habitantes</caption>'
              '<thead><tr><th scope="col">Distrito</th><th scope="col">Terrazas</th><th scope="col">Habitantes</th>'
              f'<th scope="col">Por 10.000 hab.</th></tr></thead><tbody>{body}</tbody>{foot}</table></div>'
            + ''.join(f'<p>{escape(text)}</p>' for text in density_observations(rows))
            + '<p class="small">Cuenta todos los registros de terraza del corte final, en cualquier estado. La población es la empadronada (residentes): '
              'no incluye a quienes trabajan, estudian o hacen turismo en el distrito, así que en zonas céntricas la cifra por habitante sale alta '
              'sin que eso mida saturación ni demanda. Las fechas de las dos fuentes no coinciden.</p>'
            + f'<p class="small">Población: Ayuntamiento de Madrid, <a href="{escape(source["dataset"])}">{escape(source["description"])}</a>, '
              f'licencia CC BY 4.0. <a href="{DENSITY_CSV}">Descargar la tabla en CSV</a>.</p>')


def render_density_csv(data, digest):
    context = data['districts']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['distrito', 'terrazas_registradas', 'poblacion_empadronada', 'terrazas_por_10000_hab',
                     'fecha_corte_terrazas', 'fecha_padron', 'fuente_terrazas', 'fuente_poblacion', 'licencia', 'radar_sha256'])
    for district, terraces, population, rate in density_rows(data):
        writer.writerow([csv_safe(value) for value in (display(district), terraces, population, es_number(rate, 2),
                         context['terraces_date'], context['population_date'], data['meta']['source_url'],
                         context['population_source']['dataset'], 'CC BY 4.0', digest)])
    return '\ufeff' + stream.getvalue()


SERIES_PAGE = 'evolucion-terrazas-madrid.html'
SERIES_HREF = 'evolucion-terrazas-madrid'
SERIES_CSV = 'terrazas-madrid-evolucion.csv'
NO_DISTRICT = 'SIN DISTRITO'
SHORT = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def month_index(period):
    return int(period[:4]) * 12 + int(period[5:7]) - 1


def month_name(period):
    return f'{MONTHS[int(period[5:7]) - 1]} de {period[:4]}'


def signed(value, decimals=None):
    text = es_int(abs(value)) if decimals is None else es_number(abs(value), decimals)
    return ('+' if value > 0 else '−' if value < 0 else '') + text


def missing_months(months):
    first, last = month_index(months[0]['period']), month_index(months[-1]['period'])
    have = {month_index(m['period']) for m in months}
    return [f'{i // 12}-{i % 12 + 1:02}' for i in range(first, last + 1) if i not in have]


def series_svg(months):
    """Línea estática del total mensual; los meses sin publicar cortan la línea."""
    left, right, top, bottom, width, height = 46, 330, 14, 168, 340, 196
    totals = [m['total'] for m in months]
    low, high = (min(totals) // 50) * 50, -(-max(totals) // 50) * 50
    if high == low:
        high = low + 50
    first, last = month_index(months[0]['period']), month_index(months[-1]['period'])
    x = lambda period: left + (right - left) * (month_index(period) - first) / max(last - first, 1)
    y = lambda value: bottom - (bottom - top) * (value - low) / (high - low)
    parts = [f'<svg class="line-chart" viewBox="0 0 {width} {height}" role="img" aria-labelledby="line-title line-desc">'
             '<title id="line-title">Terrazas registradas en Madrid cada mes</title>'
             f'<desc id="line-desc">De {es_int(totals[0])} en {month_name(months[0]["period"])} a {es_int(totals[-1])} en '
             f'{month_name(months[-1]["period"])}. La tabla siguiente tiene todos los valores.</desc>']
    for value in (low, (low + high) // 2, high):
        parts.append(f'<line class="grid" x1="{left}" x2="{right}" y1="{y(value):.1f}" y2="{y(value):.1f}"/>'
                     f'<text class="axis" x="{left - 4}" y="{y(value) + 3.5:.1f}">{es_int(value)}</text>')
    for index in range(first, last + 1):
        # Eje continuo: primer y último mes y cada enero, aunque ese mes no se haya publicado.
        if index in (first, last) or (index % 12 == 0 and min(index - first, last - index) >= 5):
            period = f'{index // 12}-{index % 12 + 1:02}'
            anchor = ' start' if index == first else ' end' if index == last else ''
            parts.append(f'<text class="axis-x{anchor}" x="{x(period):.1f}" y="{bottom + 16}">{SHORT[index % 12]} {period[2:4]}</text>')
    path, previous = [], None
    for month in months:
        command = 'L' if previous is not None and month_index(month['period']) - month_index(previous) == 1 else 'M'
        path.append(f'{command}{x(month["period"]):.1f},{y(month["total"]):.1f}')
        previous = month['period']
    parts.append(f'<path class="series" d="{" ".join(path)}"/>')
    for month in months:
        parts.append(f'<g><title>{month_name(month["period"]).capitalize()}: {es_int(month["total"])} terrazas registradas</title>'
                     f'<circle class="point" cx="{x(month["period"]):.1f}" cy="{y(month["total"]):.1f}" r="4"/></g>')
    parts.append('</svg>')
    return ''.join(parts)


def series_observations(months):
    first, last = months[0], months[-1]
    change = last['total'] - first['total']
    observations = [f'Entre {month_name(first["period"])} y {month_name(last["period"])}, el registro pasa de {es_int(first["total"])} '
                    f'a {es_int(last["total"])} terrazas ({signed(change)}; {signed(100 * change / first["total"], 1)} %).']
    previous_year = f'{int(last["period"][:4]) - 1}{last["period"][4:]}'
    same = next((m for m in months if m['period'] == previous_year), None)
    if same:
        delta = last['total'] - same['total']
        observations.append(f'Respecto al mismo mes del año anterior ({month_name(previous_year)}: {es_int(same["total"])}), '
                            f'la diferencia es de {signed(delta)} terrazas ({signed(100 * delta / same["total"], 1)} %).')
    peak = max(months, key=lambda m: (m['total'], m['period']))
    trough = min(months, key=lambda m: (m['total'], m['period']))
    observations.append(f'El máximo de la serie es {month_name(peak["period"])} ({es_int(peak["total"])}) y el mínimo, '
                        f'{month_name(trough["period"])} ({es_int(trough["total"])}).')
    return observations


def district_changes(months):
    first, last = months[0]['districts'], months[-1]['districts']
    names = sorted((set(first) | set(last)) - {NO_DISTRICT})
    rows = [(name, first.get(name, 0), last.get(name, 0)) for name in names]
    return sorted(rows, key=lambda row: (-(row[2] - row[1]), row[0]))


def render_series_page(data):
    meta, months = data['meta'], data['series']['months']
    origin = ORGANIZATION['url']
    first, last = months[0], months[-1]
    span = f'{month_name(first["period"])} – {month_name(last["period"])}'
    title = f'Evolución de las terrazas registradas en Madrid ({span}) | Pulso Local'
    change = last['total'] - first['total']
    description = (f'Terrazas de hostelería registradas en Madrid mes a mes: de {es_int(first["total"])} en {month_name(first["period"])} '
                   f'a {es_int(last["total"])} en {month_name(last["period"])}, con la variación por distrito. Datos abiertos del Ayuntamiento.')
    gaps = missing_months(months)
    rows, previous = [], None
    for month in months:
        delta = '' if previous is None else signed(month['total'] - previous['total'])
        note = ' *' if previous is not None and month_index(month['period']) - month_index(previous['period']) > 1 else ''
        loaded = ', '.join(es_date(value) for value in month['load_dates']) or '—'
        rows.append(f'<tr><th scope="row">{SHORT[int(month["period"][5:7]) - 1]} {month["period"][:4]}</th><td>{es_int(month["total"])}</td>'
                    f'<td>{delta}{note}</td><td>{escape(loaded)}</td></tr>')
        previous = month
    district_rows = ''.join(f'<tr><th scope="row">{escape(display(name))}</th><td>{es_int(a)}</td><td>{es_int(b)}</td><td>{signed(b - a)}</td></tr>'
                            for name, a, b in district_changes(months))
    with_gap = [m for m in months if m['districts'].get(NO_DISTRICT)]
    breadcrumb = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Pulso Local', 'item': origin},
        {'@type': 'ListItem', 'position': 2, 'name': 'Evolución de las terrazas de Madrid', 'item': origin + SERIES_HREF}]}
    gap_text = (f'<p class="small">No hay corte de {", ".join(month_name(g) for g in gaps)} en el catálogo del Ayuntamiento; '
                'la línea se interrumpe y la variación marcada con * se calcula respecto al último mes publicado.</p>') if gaps else ''
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="muestra.css"><link rel="icon" href="favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{ld_json(breadcrumb)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="./">Pulso Local</a> / Evolución</p></nav>
<h1>Evolución de las terrazas registradas en Madrid</h1>
<p class="lead">{escape(span.capitalize())} · {plural(len(months), "corte mensual", "cortes mensuales")} del registro municipal · {signed(change)} terrazas</p></header>
<p class="notice">Cuenta registros de terraza en el censo municipal, no terrazas funcionando: un registro puede corresponder a una terraza suspendida o de temporada, y los cambios pueden deberse a correcciones administrativas.</p>
<h2>Terrazas registradas cada mes</h2>
{series_svg(months)}
{''.join(f'<p>{escape(text)}</p>' for text in series_observations(months))}
<div class="table-wrap"><table><caption>Terrazas registradas por mes en el censo de locales y terrazas de Madrid</caption>
<thead><tr><th scope="col">Mes</th><th scope="col">Terrazas</th><th scope="col">Variación</th><th scope="col">Fecha de carga</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{gap_text}
<h2>Variación por distrito</h2>
<p>Diferencia entre el primer y el último corte de la serie, ordenada de mayor subida a mayor bajada.</p>
<div class="table-wrap"><table><caption>Terrazas registradas por distrito en {escape(month_name(first["period"]))} y {escape(month_name(last["period"]))}</caption>
<thead><tr><th scope="col">Distrito</th><th scope="col">{escape(SHORT[int(first["period"][5:7]) - 1])} {first["period"][:4]}</th><th scope="col">{escape(SHORT[int(last["period"][5:7]) - 1])} {last["period"][:4]}</th><th scope="col">Variación</th></tr></thead>
<tbody>{district_rows}</tbody></table></div>
{f'<p class="small">{plural(len(with_gap), "corte de la serie incluye", "cortes de la serie incluyen")} registros sin distrito '
 f'(el último, {escape(month_name(with_gap[-1]["period"]))}, con {es_int(with_gap[-1]["districts"][NO_DISTRICT])}). Se cuentan en el total, pero no en esta tabla.</p>' if with_gap else ''}
<h2>Cómo leer estos datos</h2>
<p>Cada punto es el número de identificadores de terraza distintos en el CSV mensual que publica el Ayuntamiento. La fecha del mes es la que indica el propio Ayuntamiento; la fecha de carga real del fichero puede ser otra y se muestra en la tabla.</p>
<p>Una subida no prueba que hayan abierto terrazas ni una bajada que hayan cerrado: el registro también cambia por altas y bajas administrativas, correcciones o cambios de periodo. Para ver qué terrazas concretas cambian entre los dos últimos cortes, consulta el <a href="./#radar">radar</a> y la <a href="{DISTRICT_HREF}">página por distrito</a>.</p>
<p><a href="{GUIDE_HREF}">Guía: cómo leer el censo de terrazas de Madrid</a> · <a href="{SERIES_CSV}">Descargar la serie por mes y distrito en CSV</a></p>
<h2>Procedencia y licencia</h2><p>Ayuntamiento de Madrid, <a href="{escape(meta['source_url'])}">Censo de locales, sus actividades y terrazas de hostelería y restauración. Histórico</a>, licencia <a href="{LICENSE_DEED}">CC BY 4.0</a>. Cada mes se incorpora con su recurso, tamaño y huella SHA-256; solo se publican recuentos agregados.</p>
<footer><p><a href="./">Volver al radar de Pulso Local</a> · <a href="{DISTRICT_HREF}">Terrazas por distrito</a> · <a href="{GUIDE_HREF}">Cómo leer el censo de terrazas</a></p></footer></main></body></html>'''


def render_series_csv(data, digest):
    months = data['series']['months']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['mes', 'distrito', 'terrazas_registradas', 'recurso', 'fuente', 'licencia', 'radar_sha256'])
    for month in months:
        for name, count in [('TOTAL', month['total']), *sorted(month['districts'].items())]:
            label = name if name in ('TOTAL', NO_DISTRICT) else display(name)
            writer.writerow([csv_safe(value) for value in (month['period'], label, count, month['resource_id'],
                                                           data['series']['source_url'], 'CC BY 4.0', digest)])
    return '\ufeff' + stream.getvalue()


BARRIO_PAGE = 'terrazas-madrid-por-barrio.html'
BARRIO_HREF = 'terrazas-madrid-por-barrio'
BARRIO_CSV = 'terrazas-madrid-barrios.csv'
MIN_RATE_POPULATION = 5000  # por debajo, la tasa por habitante de un barrio es demasiado sensible


def barrio_rows(data):
    """(distrito, nombre, terrazas, población, tasa por 10.000, terrazas un año antes o None)."""
    context = data.get('districts') or {}
    if not context.get('barrios'):
        return [], None
    before = None
    months = (data.get('series') or {}).get('months') or []
    if months:
        target = f'{int(months[-1]["period"][:4]) - 1}{months[-1]["period"][4:]}'
        before = next((m for m in months if m['period'] == target), None)
    rows = []
    for row in context['barrios']:
        district = row['key'].split('|')[0]
        previous = before['barrios'].get(row['key'], 0) if before else None
        rows.append((district, row['name'], row['terraces'], row['population'],
                     10000 * row['terraces'] / row['population'], previous))
    return rows, before


def render_barrio_page(data):
    meta = data['meta']
    rows, before = barrio_rows(data)
    origin = ORGANIZATION['url']
    date = long_date(data['districts']['terraces_date'])
    by_count = sorted(rows, key=lambda r: (-r[2], r[1]))
    ranked = sorted((r for r in rows if r[3] >= MIN_RATE_POPULATION), key=lambda r: (-r[4], r[1]))
    small = sum(r[3] < MIN_RATE_POPULATION for r in rows)
    without = [r for r in rows if r[2] == 0]
    title = f'Terrazas de Madrid por barrio: cuántas hay y por habitante ({date}) | Pulso Local'
    description = (f'Terrazas registradas en los {len(rows)} barrios de Madrid a {date}: número, terrazas por cada 10.000 habitantes'
                   f'{" y variación en un año" if before else ""}. Datos abiertos del Ayuntamiento.')
    top = lambda items: ''.join(f'<li>{escape(r[1])} ({escape(display(r[0]))}): {es_int(r[2])} terrazas'
                                f'{"" if items is by_count else f", {es_number(r[4])} por cada 10.000 habitantes"}</li>' for r in items[:10])
    change_head = f'<th scope="col">Hace un año</th><th scope="col">Variación</th>' if before else ''
    body = ''.join(
        f'<tr><th scope="row">{escape(r[1])}</th><td>{escape(display(r[0]))}</td><td>{es_int(r[2])}</td><td>{es_int(r[3])}</td>'
        f'<td>{es_number(r[4])}{"*" if r[3] < MIN_RATE_POPULATION else ""}</td>'
        + (f'<td>{es_int(r[5])}</td><td>{signed(r[2] - r[5])}</td>' if before else '') + '</tr>'
        for r in sorted(rows, key=lambda r: (r[0], r[1])))
    observations = [f'{by_count[0][1]} ({display(by_count[0][0])}) es el barrio con más terrazas registradas: {es_int(by_count[0][2])}.',
                    f'Los diez barrios con más terrazas suman {es_int(sum(r[2] for r in by_count[:10]))} de las '
                    f'{es_int(sum(r[2] for r in rows))} ({es_number(100 * sum(r[2] for r in by_count[:10]) / sum(r[2] for r in rows), 0)} %).']
    if without:
        observations.append(f'{plural(len(without), "barrio no tiene", "barrios no tienen")} ninguna terraza registrada: '
                            f'{", ".join(r[1] for r in without)}.')
    if before:
        grew = sorted(rows, key=lambda r: (-(r[2] - r[5]), r[1]))[0]
        fell = sorted(rows, key=lambda r: ((r[2] - r[5]), r[1]))[0]
        changes = []
        if grew[2] - grew[5] > 0:
            changes.append(f'el barrio con mayor subida es {grew[1]} ({signed(grew[2] - grew[5])})')
        if fell[2] - fell[5] < 0:
            changes.append(f'el de mayor bajada, {fell[1]} ({signed(fell[2] - fell[5])})')
        if changes:
            observations.append(f'Respecto a {month_name(before["period"])}, ' + ' y '.join(changes) + '.')
    breadcrumb = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Pulso Local', 'item': origin},
        {'@type': 'ListItem', 'position': 2, 'name': 'Terrazas de Madrid por barrio', 'item': origin + BARRIO_HREF}]}
    source = data['districts']['population_source']
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="muestra.css"><link rel="icon" href="favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{ld_json(breadcrumb)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="./">Pulso Local</a> / Terrazas por barrio</p></nav>
<h1>Terrazas de Madrid por barrio</h1>
<p class="lead">{plural(len(rows), "barrio", "barrios")} · registros de terraza a {escape(date)} · población a {escape(long_date(data["districts"]["population_date"]))}</p></header>
<p class="notice">Cuenta registros de terraza en el censo municipal, no terrazas funcionando, y no mide saturación ni molestias: la población empadronada no incluye a quienes trabajan o hacen turismo en el barrio.</p>
<h2>Barrios con más terrazas</h2><ol>{top(by_count)}</ol>
<h2>Barrios con más terrazas por habitante</h2>
<p>Solo barrios con al menos {es_int(MIN_RATE_POPULATION)} habitantes: con menos, una sola terraza mueve mucho la cifra ({plural(small, "barrio queda", "barrios quedan")} fuera de este ranking y se marcan con * en la tabla).</p><ol>{top(ranked)}</ol>
<h2>Qué se observa</h2>{''.join(f'<p>{escape(text)}</p>' for text in observations)}
<h2>Todos los barrios</h2>
<div class="table-wrap"><table><caption>Terrazas registradas, población y terrazas por cada 10.000 habitantes por barrio, ordenados por distrito</caption>
<thead><tr><th scope="col">Barrio</th><th scope="col">Distrito</th><th scope="col">Terrazas</th><th scope="col">Habitantes</th><th scope="col">Por 10.000 hab.</th>{change_head}</tr></thead>
<tbody>{body}</tbody></table></div>
<p class="small">* Barrio con menos de {es_int(MIN_RATE_POPULATION)} habitantes: tasa poco estable.{f" «Hace un año» es el corte de {escape(month_name(before['period']))}." if before else ""} Los nombres de barrio del censo de terrazas se han unificado con los del padrón (por ejemplo, «Casco H. Vallecas» o «San Andrés», nombre antiguo de Villaverde Alto).</p>
<p><a href="{BARRIO_CSV}">Descargar la tabla en CSV</a> · <a href="{DISTRICT_HREF}">Terrazas por distrito</a> · <a href="{SERIES_HREF}">Evolución mes a mes</a> · <a href="{GUIDE_HREF}">Cómo leer el censo de terrazas</a></p>
<h2>Procedencia y licencia</h2><p>Ayuntamiento de Madrid: <a href="{escape(meta['source_url'])}">censo de locales y terrazas (histórico)</a> y <a href="{escape(source['dataset'])}">{escape(source['description'])}</a>, licencia <a href="{LICENSE_DEED}">CC BY 4.0</a>. Solo se publican recuentos agregados por barrio.</p>
<footer><p><a href="./">Volver al radar de Pulso Local</a> · <a href="{DISTRICT_HREF}">Terrazas por distrito</a> · <a href="{SERIES_HREF}">Evolución</a></p></footer></main></body></html>'''


def render_barrio_csv(data, digest):
    rows, before = barrio_rows(data)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['distrito', 'barrio', 'terrazas_registradas', 'poblacion_empadronada', 'terrazas_por_10000_hab',
                     'terrazas_hace_un_ano', 'fecha_corte', 'fecha_padron', 'licencia', 'radar_sha256'])
    for r in sorted(rows, key=lambda r: (r[0], r[1])):
        writer.writerow([csv_safe(v) for v in (display(r[0]), r[1], r[2], r[3], es_number(r[4], 2), '' if r[5] is None else r[5],
                                               data['districts']['terraces_date'], data['districts']['population_date'], 'CC BY 4.0', digest)])
    return '\ufeff' + stream.getvalue()


SURFACE_PAGE = 'superficie-terrazas-madrid.html'
SURFACE_HREF = 'superficie-terrazas-madrid'
SURFACE_CSV = 'terrazas-madrid-superficie.csv'


def surface_rows(data):
    """(distrito, terrazas, anuales, m² temporada, m² resto del año, sillas temporada, población) del corte final."""
    months = (data.get('series') or {}).get('months') or []
    context = data.get('districts') or {}
    if not months or not months[-1].get('capacity') or not context.get('rows'):
        return []
    capacity, population = months[-1]['capacity'], {r['district']: r['population'] for r in context['rows']}
    if set(capacity) - set(population) - {'SIN DISTRITO'}:
        raise ValueError('Distritos con superficie y sin población: revisión necesaria')
    return [(name, months[-1]['districts'][name], c['anuales'], c['m2_es'], c['m2_ra'], c['sillas_es'], population[name])
            for name, c in sorted(capacity.items()) if name in population]


def bars_svg(items, title, desc, label_id):
    """Barras horizontales estáticas: items = [(etiqueta, valor, texto del valor, tooltip)], ya ordenados."""
    label_x, bar_x, bar_w, row_h, bar_h, top, r = 128, 132, 168, 22, 14, 10, 4
    height = top + row_h * len(items) + 6
    scale = bar_w / (max((value for _, value, _, _ in items), default=1) or 1)
    parts = [f'<svg class="bars" viewBox="0 0 340 {height}" role="img" aria-labelledby="{label_id}-t {label_id}-d">'
             f'<title id="{label_id}-t">{escape(title)}</title><desc id="{label_id}-d">{escape(desc)}</desc>']
    for index, (label, value, text, tip) in enumerate(items):
        y = top + index * row_h
        width = max(value * scale, 2 * r)
        path = (f'M{bar_x},{y} h{width - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} '
                f'a{r},{r} 0 0 1 -{r},{r} h-{width - r:.1f} z')
        parts.append(f'<g><title>{escape(tip)}</title><text class="bar-label" x="{label_x}" y="{y + 11}">{escape(label)}</text>'
                     f'<path class="bar" d="{path}"/><text class="bar-value" x="{bar_x + width + 4:.1f}" y="{y + 11}">{escape(text)}</text></g>')
    parts.append('</svg>')
    return ''.join(parts)


def surface_totals(month):
    c = month['capacity']
    return {'total': month['total'], 'anuales': sum(v['anuales'] for v in c.values()),
            'm2_es': sum(v['m2_es'] for v in c.values()), 'm2_ra': sum(v['m2_ra'] for v in c.values()),
            'sillas_es': sum(v['sillas_es'] for v in c.values())}


def pct(part, whole, decimals=0):
    return es_number(100 * part / whole, decimals)


def render_surface_page(data):
    meta, months = data['meta'], [m for m in data['series']['months'] if m.get('capacity')]
    rows = surface_rows(data)
    origin = ORGANIZATION['url']
    last, first = surface_totals(months[-1]), surface_totals(months[0])
    population = sum(r[6] for r in rows)
    date = month_name(months[-1]['period'])
    title = f'Superficie y sillas de las terrazas de Madrid por distrito ({date}) | Pulso Local'
    description = (f'Metros cuadrados y sillas autorizados a las terrazas de Madrid por distrito en {date}: '
                   f'{es_int(last["m2_es"])} m² en temporada, {es_int(last["sillas_es"])} sillas, y su evolución desde {month_name(months[0]["period"])}.')
    ranked = sorted(rows, key=lambda r: (-1000 * r[3] / r[6], r[0]))
    chart = bars_svg([(display(r[0]), 1000 * r[3] / r[6], es_number(1000 * r[3] / r[6]),
                       f'{display(r[0])}: {es_int(r[3])} m² en temporada para {es_int(r[6])} habitantes') for r in ranked],
                     'Metros cuadrados de terraza en temporada por cada 1.000 habitantes, por distrito',
                     f'De {display(ranked[0][0])} ({es_number(1000 * ranked[0][3] / ranked[0][6])}) a {display(ranked[-1][0])} '
                     f'({es_number(1000 * ranked[-1][3] / ranked[-1][6])}). La tabla siguiente tiene todos los valores.', 'sup')
    body = ''.join(f'<tr><th scope="row">{escape(display(r[0]))}</th><td>{es_int(r[1])}</td><td>{pct(r[2], r[1])} %</td>'
                   f'<td>{es_int(r[3])}</td><td>{es_int(r[4])}</td><td>{es_int(r[5])}</td>'
                   f'<td>{es_number(1000 * r[3] / r[6])}</td><td>{es_number(r[3] / r[1])}</td></tr>' for r in ranked)
    foot = (f'<tfoot><tr><th scope="row">Madrid</th><td>{es_int(last["total"])}</td><td>{pct(last["anuales"], last["total"])} %</td>'
            f'<td>{es_int(last["m2_es"])}</td><td>{es_int(last["m2_ra"])}</td><td>{es_int(last["sillas_es"])}</td>'
            f'<td>{es_number(1000 * last["m2_es"] / population)}</td><td>{es_number(last["m2_es"] / last["total"])}</td></tr></tfoot>')
    evolution = ''.join(
        f'<tr><th scope="row">{SHORT[int(m["period"][5:7]) - 1]} {m["period"][:4]}</th><td>{es_int(t["total"])}</td>'
        f'<td>{pct(t["anuales"], t["total"])} %</td><td>{es_int(t["m2_es"])}</td><td>{es_int(t["sillas_es"])}</td></tr>'
        for m, t in ((m, surface_totals(m)) for m in months))
    biggest = max(rows, key=lambda r: (r[3], r[0]))
    observations = [
        f'En {date} el registro autoriza {es_int(last["m2_es"])} m² de terraza en temporada y {es_int(last["sillas_es"])} sillas; '
        f'de media, {es_number(last["m2_es"] / last["total"])} m² y {es_number(last["sillas_es"] / last["total"])} sillas por terraza.',
        f'{display(biggest[0])} es el distrito con más superficie ({es_int(biggest[3])} m²) y '
        + ('también ' if ranked[0][0] == biggest[0] else f'{display(ranked[0][0])} ')
        + f'el que más tiene por habitante ({es_number(1000 * ranked[0][3] / ranked[0][6])} m² por cada 1.000).',
        f'El {pct(last["anuales"], last["total"])} % de las terrazas registradas son anuales; el resto, estacionales, '
        'que no tienen superficie autorizada fuera de temporada.',
        f'Desde {month_name(months[0]["period"])}: terrazas {signed(last["total"] - first["total"])} ({signed(100 * (last["total"] - first["total"]) / first["total"], 1)} %), '
        f'anuales {signed(last["anuales"] - first["anuales"])}, superficie en temporada {signed(last["m2_es"] - first["m2_es"])} m² '
        f'({signed(100 * (last["m2_es"] - first["m2_es"]) / first["m2_es"], 1)} %) y sillas {signed(last["sillas_es"] - first["sillas_es"])}. '
        f'La superficie media por terraza pasa de {es_number(first["m2_es"] / first["total"])} a {es_number(last["m2_es"] / last["total"])} m².']
    breadcrumb = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Pulso Local', 'item': origin},
        {'@type': 'ListItem', 'position': 2, 'name': 'Superficie de las terrazas de Madrid', 'item': origin + SURFACE_HREF}]}
    source = data['districts']['population_source']
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="muestra.css"><link rel="icon" href="favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{ld_json(breadcrumb)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="./">Pulso Local</a> / Superficie</p></nav>
<h1>Superficie y sillas de las terrazas de Madrid por distrito</h1>
<p class="lead">{escape(date.capitalize())} · {es_int(last["m2_es"])} m² y {es_int(last["sillas_es"])} sillas autorizados en temporada · {es_int(last["total"])} terrazas registradas</p></header>
<p class="notice">Son los metros cuadrados y las sillas que figuran como autorizados en el censo municipal, no mediciones sobre el terreno ni ocupación real. «Temporada» es el periodo estacional que indica el registro; «resto del año», el resto, en el que solo tienen superficie las terrazas anuales.</p>
<h2>Metros cuadrados de terraza por cada 1.000 habitantes</h2>
{chart}
<div class="table-wrap"><table><caption>Terrazas, superficie y sillas autorizadas por distrito en {escape(date)}, ordenadas por m² en temporada por cada 1.000 habitantes</caption>
<thead><tr><th scope="col">Distrito</th><th scope="col">Terrazas</th><th scope="col">Anuales</th><th scope="col">m² temporada</th><th scope="col">m² resto del año</th><th scope="col">Sillas temporada</th><th scope="col">m² por 1.000 hab.</th><th scope="col">m² por terraza</th></tr></thead>
<tbody>{body}</tbody>{foot}</table></div>
<h2>Qué se observa</h2>{''.join(f'<p>{escape(text)}</p>' for text in observations)}
<h2>Evolución mensual</h2>
<div class="table-wrap"><table><caption>Terrazas registradas, porcentaje de anuales, superficie y sillas en temporada por mes</caption>
<thead><tr><th scope="col">Mes</th><th scope="col">Terrazas</th><th scope="col">Anuales</th><th scope="col">m² temporada</th><th scope="col">Sillas temporada</th></tr></thead>
<tbody>{evolution}</tbody></table></div>
<h2>Cómo leer estos datos</h2>
<p>La superficie es la suma de los metros cuadrados autorizados a cada terraza del registro, con dos decimales en origen y redondeada aquí al metro por distrito. Se suman todas las terrazas del registro, también las que figuran en suspensión temporal. El cambio de superficie entre meses puede deberse a nuevas autorizaciones, bajas o correcciones del registro, no necesariamente a cambios en la calle.</p>
<p>La población es la empadronada a {escape(long_date(data["districts"]["population_date"]))}: no incluye a quienes trabajan o hacen turismo en el distrito, así que la cifra por habitante no mide saturación. Sobre la normativa de terrazas, consulta el Ayuntamiento: esta página no la interpreta.</p>
<p><a href="{SURFACE_CSV}">Descargar la tabla por distrito en CSV</a> · <a href="{DISTRICT_HREF}">Terrazas por distrito</a> · <a href="{BARRIO_HREF}">Por barrio</a> · <a href="{SERIES_HREF}">Evolución</a> · <a href="{GUIDE_HREF}">Cómo leer el censo</a></p>
<h2>Procedencia y licencia</h2><p>Ayuntamiento de Madrid: <a href="{escape(meta['source_url'])}">censo de locales y terrazas (histórico)</a>, campos Superficie_ES, Superficie_RA, sillas_es y desc_periodo_terraza, y <a href="{escape(source['dataset'])}">{escape(source['description'])}</a>. Licencia <a href="{LICENSE_DEED}">CC BY 4.0</a>. Solo se publican sumas por distrito.</p>
<footer><p><a href="./">Volver al radar de Pulso Local</a> · <a href="{DISTRICT_HREF}">Terrazas por distrito</a> · <a href="{SERIES_HREF}">Evolución</a></p></footer></main></body></html>'''


def render_surface_csv(data, digest):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';', lineterminator='\r\n')
    writer.writerow(['distrito', 'terrazas', 'terrazas_anuales', 'm2_temporada', 'm2_resto_del_ano', 'sillas_temporada',
                     'poblacion_empadronada', 'm2_temporada_por_1000_hab', 'mes', 'licencia', 'radar_sha256'])
    period = data['series']['months'][-1]['period']
    for r in surface_rows(data):
        writer.writerow([csv_safe(v) for v in (display(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], es_number(1000 * r[3] / r[6], 2),
                                               period, 'CC BY 4.0', digest)])
    return '\ufeff' + stream.getvalue()


def render_district_page(data):
    meta, changes = data['meta'], data['changes']
    kinds, rows = district_stats(changes)
    origin = ORGANIZATION['url']
    density = bool(density_rows(data))
    heading = ('Terrazas de Madrid por distrito: por habitante y cambios en el registro' if density
               else 'Terrazas de Madrid por distrito: cambios en el registro')
    title = f'{heading} ({period(meta)}) | Pulso Local'
    description = (f'{plural(len(changes), "cambio", "cambios")} en el registro municipal de terrazas de Madrid entre el {es_date(meta["from_date"])} '
                   f'y el {es_date(meta["to_date"])}, por distrito y tipo{", con terrazas por cada 10.000 habitantes" if density else ""}. Un cambio en el registro no prueba que un local haya empezado o dejado de funcionar.')
    head = ''.join(f'<th scope="col">{escape(LABELS[kind])}</th>' for kind in kinds)
    body = ''.join(f'<tr><th scope="row">{escape(district)}</th>' + ''.join(f'<td>{split[kind]}</td>' for kind in kinds)
                   + f'<td>{total}</td></tr>' for district, total, split in rows)
    foot = (f'<tfoot><tr><th scope="row">Total</th>' + ''.join(f'<td>{sum(split[kind] for _, _, split in rows)}</td>' for kind in kinds)
            + f'<td>{len(changes)}</td></tr></tfoot>') if rows else ''
    observations = []
    if rows:
        best = [district for district, total, _ in rows if total == rows[0][1]]
        share = round(100 * rows[0][1] / len(changes))
        observations.append(f'{" y ".join(best)} {"concentra" if len(best) == 1 else "concentran cada uno"} {plural(rows[0][1], "cambio", "cambios")} '
                            f'({share} % del total{" cada uno" if len(best) > 1 else ""}).')
        top3 = sum(total for _, total, _ in rows[:3])
        if len(rows) > 3:
            observations.append(f'Los tres primeros distritos de la tabla suman {top3} de los {len(changes)} cambios.')
        singles = sum(total == 1 for _, total, _ in rows)
        if singles:
            observations.append(f'{plural(singles, "distrito tiene", "distritos tienen")} un solo cambio, una cifra demasiado pequeña para sacar tendencias.')
        if 'entrada' in kinds:
            most = max(split['entrada'] for _, _, split in rows)
            leaders = [district for district, _, split in rows if split['entrada'] == most]
            if len(leaders) == 1:
                observations.append(f'El distrito con más terrazas que {PHRASES["entrada"][1]} es {leaders[0]} ({most}).')
    breadcrumb = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Pulso Local', 'item': origin},
        {'@type': 'ListItem', 'position': 2, 'name': 'Terrazas de Madrid por distrito', 'item': origin + DISTRICT_HREF}]}
    license_url = meta.get('license_url')
    license_text = escape(meta.get('license', 'No indicada'))
    license_link = f'<a href="{escape(LICENSE_DEED if license_url == "https://creativecommons.org/licenses/by/4.0/" else license_url)}">{license_text}</a>' if license_url else license_text
    demo = '<p class="notice">DEMO: datos sintéticos, no hechos reales.</p>' if meta['mode'] == 'synthetic' else ''
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="muestra.css"><link rel="icon" href="favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{ld_json(breadcrumb)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="./">Pulso Local</a> / Terrazas por distrito</p></nav>
<h1>{escape(heading)}</h1>
<p class="lead">Cortes del {escape(es_date(meta['from_date']))} y del {escape(es_date(meta['to_date']))} · {plural(len(changes), "cambio", "cambios")} en {plural(len(rows), "distrito", "distritos")}</p></header>{demo}
<p class="notice">Diferencias administrativas en el registro municipal: no confirman que un local haya empezado o dejado de funcionar ni describen su actividad real.</p>
<h2>Qué es el registro y qué significa cada cambio</h2>
<p>El Ayuntamiento de Madrid publica en datos abiertos el censo de locales y actividades, que incluye las terrazas de hostelería. Pulso Local compara dos cortes de ese registro e identifica qué terrazas difieren entre ellos.</p>
<ul><li><strong>{escape(LABELS['entrada'])}</strong>: la terraza aparece en el corte final y no en el inicial.</li>
<li><strong>{escape(LABELS['salida'])}</strong>: la terraza estaba en el corte inicial y no aparece en el corte final.</li>
<li><strong>{escape(LABELS['cambio_estado'])}</strong>: la terraza está en los dos cortes, pero cambia su estado, su periodo, el local vinculado o el barrio.</li>
<li><strong>{escape(LABELS['cambio_actividad'])}</strong>: la terraza está en los dos cortes con otra actividad registrada.</li></ul>
<h2>Cambios por distrito</h2><p>{escape(breakdown(changes))}.{escape(coverage(meta, changes))}</p>
<div class="table-wrap"><table><caption>Cambios en el registro de terrazas por distrito y tipo, del {escape(es_date(meta['from_date']))} al {escape(es_date(meta['to_date']))}, ordenados por total</caption>
<thead><tr><th scope="col">Distrito</th>{head}<th scope="col">Total</th></tr></thead><tbody>{body}</tbody>{foot}</table></div>
<h2>Qué se observa</h2>{''.join(f'<p>{escape(text)}</p>' for text in observations) or '<p>No hay cambios publicados en esta comparación.</p>'}
{render_density(data)}
<h2>Cómo leer estos datos</h2>
<p>Un cambio en el registro no prueba que un local haya empezado o dejado de funcionar: puede deberse a correcciones, reclasificaciones o al ritmo de actualización de la fuente. La fecha del corte no es la fecha del cambio real.</p>
<p>{escape(meta.get('coverage_note', ''))}</p><p>{escape(meta.get('selection_note', ''))}</p><p>{escape(meta.get('privacy_note', ''))}</p>
<p>Las cifras de cambios por distrito son pequeñas: no sirven para comparar la actividad hostelera entre zonas ni para estimar demanda.</p>
<p><a href="{GUIDE_HREF}">Guía: cómo leer el censo de terrazas de Madrid y qué significa cada cambio</a></p>
<h2>Procedencia y licencia</h2><p>{escape(meta.get('attribution', 'Datos sintéticos de demostración'))}</p>
<p><a href="{escape(meta['source_url'])}">Fuente oficial: conjunto de datos del Ayuntamiento de Madrid</a>. Licencia {license_link}. Datos saneados generados el {escape(es_date(meta['generated_at'][:10]))}.</p>
<footer><p><a href="./">Volver al radar de Pulso Local</a> · <a href="muestra">Informe gratuito con cada registro y CSV</a> · <a href="{GUIDE_HREF}">Cómo leer el censo de terrazas</a>{f' · <a href="{SERIES_HREF}">Evolución mes a mes</a>' if data.get('series') else ''}{f' · <a href="{BARRIO_HREF}">Terrazas por barrio</a>' if (data.get('districts') or {}).get('barrios') else ''}{f' · <a href="{SURFACE_HREF}">Superficie y sillas</a>' if surface_rows(data) else ''}</p></footer></main></body></html>'''


def sample_files(raw, index=None):
    """Render exactly the validated bytes included in this build.

    Con la portada del radar (bytes), devuelve también su versión con el resumen estático.
    """
    data = validate_radar(json.loads(raw))
    digest = hashlib.sha256(raw).hexdigest()
    files = {'muestra.html': render_html(data, digest).encode('utf-8'),
             'muestra.css': CSS.encode('utf-8'),
             'pulso-muestra.csv': render_csv(data, digest).encode('utf-8'),
             DISTRICT_PAGE: render_district_page(data).encode('utf-8'),
             GUIDE_PAGE: (ROOT / 'site' / GUIDE_PAGE).read_bytes(),
             'og.png': (ROOT / 'site' / 'og.png').read_bytes()}
    if data.get('districts'):
        files[DENSITY_CSV] = render_density_csv(data, digest).encode('utf-8')
    if (data.get('districts') or {}).get('barrios'):
        files[BARRIO_PAGE] = render_barrio_page(data).encode('utf-8')
        files[BARRIO_CSV] = render_barrio_csv(data, digest).encode('utf-8')
    if surface_rows(data):
        files[SURFACE_PAGE] = render_surface_page(data).encode('utf-8')
        files[SURFACE_CSV] = render_surface_csv(data, digest).encode('utf-8')
    if data.get('series'):
        files[SERIES_PAGE] = render_series_page(data).encode('utf-8')
        files[SERIES_CSV] = render_series_csv(data, digest).encode('utf-8')
    if index is not None:
        files['index.html'] = render_index(index.decode('utf-8-sig'), data).encode('utf-8')
    return files


def generate(source=ROOT / 'data/radar.json', output=ROOT / 'docs/muestras/pulso'):
    raw = Path(source).read_bytes()
    data = validate_radar(json.loads(raw))
    digest = hashlib.sha256(raw).hexdigest()
    report, export = render_html(data, digest), render_csv(data, digest)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'index.html').write_text(report, encoding='utf-8')
    (output / 'muestra.css').write_text(CSS, encoding='utf-8')
    (output / 'pulso-muestra.csv').write_bytes(export.encode('utf-8'))
    return digest

if __name__ == '__main__':
    print('Muestra generada en docs/muestras/pulso. SHA-256 entrada:', generate())
