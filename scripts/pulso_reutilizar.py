"""Página «Cómo reutilizar los datos de Pulso» (Madrid y València). Se genera desde las cabeceras reales de los CSV.

Uso: la llama scripts/pulso_valencia.py al generar la carpeta pulso-valencia/.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from factory.indexing import page_metadata  # noqa: E402
from factory.security import protect_html  # noqa: E402
from pulso_sample import escape, ld_json, sample_files  # noqa: E402

PAGE = 'reutilizar-datos.html'
URL = 'https://paniset.github.io/pulso-valencia/reutilizar-datos'
REPO = 'https://github.com/paniset/pulso-datos-abiertos'
MADRID = 'https://paniset.github.io/pulso-local-madrid/'
VALENCIA = 'https://paniset.github.io/pulso-valencia/'
LICENSE_DEED = 'https://creativecommons.org/licenses/by/4.0/deed.es'
EXTRA_CSS = 'blockquote{margin:12px 0;padding:10px 14px;border-left:4px solid #164c63;background:#f3f6f7}pre{overflow-x:auto;background:#f3f6f7;border:1px solid #c9d8de;padding:12px;font-size:13px;line-height:1.4}code{font-family:Consolas,monospace}'

# Descripción de cada columna publicada. Si un CSV gana una columna nueva, la prueba exige describirla aquí.
COLUMNS = {
    'id': 'Identificador municipal de la terraza (id_terraza).', 'local_id': 'Identificador municipal del local vinculado.',
    'district': 'Distrito.', 'neighborhood': 'Barrio.', 'activity': 'Actividad registrada (texto fijo: hostelería con terraza).',
    'type': 'Tipo de cambio entre los dos cortes: entrada, salida, cambio_estado o cambio_actividad.',
    'before': 'Estado en el corte inicial (vacío si la terraza no estaba).', 'after': 'Estado en el corte final (vacío si ya no está).',
    'changed_fields': 'Campos que cambian, separados por comas.', 'from_date': 'Fecha del corte inicial.', 'to_date': 'Fecha del corte final.',
    'source_url': 'Conjunto de datos de origen.', 'license': 'Licencia de los datos.', 'attribution': 'Texto de atribución.',
    'radar_sha256': 'Huella SHA-256 del fichero de datos con el que se generó el CSV (para comprobar la versión).',
    'interpretation': 'Recordatorio: diferencia administrativa, no apertura ni cierre confirmados.', 'mode': 'real o synthetic (demostración).',
    'distrito': 'Distrito.', 'barrio': 'Barrio.', 'terrazas_registradas': 'Registros de terraza en el censo municipal.',
    'poblacion_empadronada': 'Habitantes empadronados según el padrón municipal.',
    'terrazas_por_10000_hab': 'Terrazas registradas por cada 10.000 habitantes empadronados.',
    'fecha_corte_terrazas': 'Fecha del corte del censo de terrazas.', 'fecha_padron': 'Fecha de referencia del padrón.',
    'fuente_terrazas': 'Conjunto de datos de las terrazas.', 'fuente_poblacion': 'Conjunto de datos de la población.',
    'licencia': 'Licencia de los datos.', 'terrazas_hace_un_ano': 'Terrazas registradas en el mismo mes del año anterior.',
    'fecha_corte': 'Fecha del corte del censo.', 'terrazas': 'Terrazas registradas.', 'terrazas_anuales': 'Terrazas de periodo anual.',
    'm2_temporada': 'Metros cuadrados autorizados en periodo estacional (suma).', 'm2_resto_del_ano': 'Metros cuadrados autorizados el resto del año (solo terrazas anuales).',
    'sillas_temporada': 'Sillas autorizadas en periodo estacional (suma).', 'm2_temporada_por_1000_hab': 'Metros cuadrados en temporada por cada 1.000 habitantes.',
    'mes': 'Mes del corte (AAAA-MM).', 'recurso': 'Identificador del fichero mensual en el portal.', 'fuente': 'Conjunto de datos de origen.',
    'anio': 'Año de los recibos.', 'codigo_barrio': 'Código del barrio (distrito y barrio, como en el portal de València).',
    'recibos': 'Recibos emitidos de la tasa de mesas y sillas.', 'importe_eur': 'Importe facturado en euros (vacío si el barrio tiene menos de 5 recibos).',
    'anio_completo': '«sí» si ese año trae todos los distritos; «no» si está incompleto y no debe compararse.',
    'vulnerabilidad_global_2021': 'Nivel de vulnerabilidad global del barrio en 2021 (Alta, Media o Baja; vacío en pedanías).',
    'area_barrio_km2': 'Superficie del barrio en km² (capa de vulnerabilidad; vacío en pedanías).',
    'codigo_ine': 'Código del municipio en el INE (5 cifras).', 'municipio': 'Municipio (nombre del INE).', 'provincia': 'Provincia.',
    'habitantes': 'Población oficial del INE a 1 de enero del año indicado en anio_padron.',
    'bares': 'Inscripciones de tipo «Bares» en el Registro de Turismo.', 'restaurantes': 'Inscripciones de tipo «Restaurantes».',
    'cafeterias': 'Inscripciones de tipo «Cafeterías».', 'fecha_registro': 'Fecha de descarga del Registro de Turismo.',
    'anio_padron': 'Año de las cifras de población del INE.',
}


def headers(raw_csv):
    return raw_csv.decode('utf-8-sig').splitlines()[0].split(';')


def catalog(valencia_csv):
    """[(ciudad, archivo, url, descripción, columnas)] de todos los CSV publicados."""
    madrid = sample_files((ROOT / 'data' / 'radar.json').read_bytes())
    items = [
        ('Madrid', 'terrazas-madrid-distritos.csv', 'Terrazas registradas y población por distrito, con terrazas por cada 10.000 habitantes.'),
        ('Madrid', 'terrazas-madrid-barrios.csv', 'Lo mismo por barrio (131 barrios), con el dato de hace un año.'),
        ('Madrid', 'terrazas-madrid-superficie.csv', 'Superficie y sillas autorizadas por distrito.'),
        ('Madrid', 'terrazas-madrid-evolucion.csv', 'Terrazas registradas por mes y distrito desde octubre de 2024 (formato largo).'),
        ('Madrid', 'pulso-muestra.csv', 'Cada cambio entre los dos últimos cortes del censo, con su estado antes y después.'),
    ]
    rows = [(city, name, MADRID + name, text, headers(madrid[name])) for city, name, text in items if name in madrid]
    cyl = ROOT / 'sites' / 'paniset-github-io' / 'site' / 'pulso-castilla-y-leon' / 'hosteleria-municipios-castilla-y-leon.csv'
    if cyl.exists():
        rows.append(('Castilla y León', cyl.name, 'https://paniset.github.io/pulso-castilla-y-leon/' + cyl.name,
                     'Bares, restaurantes y cafeterías del Registro de Turismo y habitantes, para los 2.248 municipios.', headers(cyl.read_bytes())))
    rows.append(('València', 'recibos-terrazas-valencia.csv', VALENCIA + 'recibos-terrazas-valencia.csv',
                 'Recibos de la tasa de terrazas por barrio y año, con importe, código, vulnerabilidad y superficie del barrio.',
                 headers(valencia_csv)))
    return rows


def render(valencia_csv):
    rows = catalog(valencia_csv.encode('utf-8') if isinstance(valencia_csv, str) else valencia_csv)
    missing = sorted({c for *_, cols in rows for c in cols} - set(COLUMNS))
    if missing:
        raise ValueError('Columnas sin describir: ' + ', '.join(missing))
    blocks = []
    for city, name, url, text, cols in rows:
        items = ''.join(f'<li><code>{escape(c)}</code>: {escape(COLUMNS[c])}</li>' for c in cols)
        blocks.append(f'<h3>{escape(city)}: <a href="{escape(url)}">{escape(name)}</a></h3><p>{escape(text)}</p>'
                      f'<details><summary>Columnas ({len(cols)})</summary><ul>{items}</ul></details>')
    title = 'Cómo reutilizar los datos de Pulso: terrazas de Madrid y València y hostelería de Castilla y León (CSV) | Pulso'
    description = ('Guía para descargar y reutilizar los CSV de Pulso sobre terrazas de Madrid y València y hostelería de Castilla y León: columnas, licencia CC BY 4.0, '
                   'cómo citar la fuente y ejemplos para hoja de cálculo y Python.')
    article = {'@context': 'https://schema.org', '@type': 'TechArticle', 'headline': 'Cómo reutilizar los datos de Pulso: terrazas de Madrid y València y hostelería de Castilla y León',
               'dateModified': '2026-11-13', 'inLanguage': 'es', 'mainEntityOfPage': URL,
               'author': {'@type': 'Organization', 'name': 'Pulso Local'}, 'license': LICENSE_DEED}
    example = '''import csv, io, urllib.request

url = "https://paniset.github.io/pulso-valencia/recibos-terrazas-valencia.csv"
texto = urllib.request.urlopen(url).read().decode("utf-8-sig")
filas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))

# Recibos de 2025 por distrito (solo años completos)
totales = {}
for f in filas:
    if f["anio"] == "2025" and f["anio_completo"] == "sí":
        totales[f["distrito"]] = totales.get(f["distrito"], 0) + int(f["recibos"])
print(sorted(totales.items(), key=lambda par: -par[1])[:5])'''
    attribution = ('Fuente: Ajuntament de València («Recibos mesas y sillas 2020-2025»; «Vulnerabilidad por barrios 2021»), '
                   'Ayuntamiento de Madrid (censo de locales y terrazas; padrón por distrito y barrio) y Junta de Castilla y León '
                   '(Registro de Turismo), CC BY 4.0; población municipal de Castilla y León: INE. Elaboración: Pulso Local.')
    page = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}"><link rel="stylesheet" href="style.css"><link rel="icon" href="data:,">
<script type="application/ld+json">{ld_json(article)}</script></head><body><main><header><nav aria-label="Ruta"><p><a href="../">Herramientas gratuitas</a> / <a href="./">Pulso València</a> / Reutilizar los datos</p></nav>
<h1>Cómo reutilizar los datos de Pulso: Madrid, València y Castilla y León</h1>
<p class="lead">CSV gratuitos, con licencia CC BY 4.0 y código abierto. Actualizado el 13 de noviembre de 2026.</p></header>
<h2>Qué puedes hacer</h2>
<p>Puedes descargar, copiar, publicar, combinar y usar estos datos con cualquier fin, también comercial, siempre que cites la fuente. Sirven para periodismo, trabajos de clase, estudios de asociaciones vecinales o análisis propios. Los cálculos se pueden comprobar en el <a href="{REPO}">código abierto</a>.</p>
<h2>Los archivos</h2>
<p>Todos son CSV en UTF-8 con separador punto y coma, que es el formato que espera una hoja de cálculo en español. Los decimales llevan coma salvo en los identificadores y las huellas.</p>
{''.join(blocks)}
<h2>Cómo citarlos</h2>
<p>Copia este texto, o uno equivalente, junto a tu gráfico o artículo:</p>
<blockquote><p>{escape(attribution)}</p></blockquote>
<h2>Abrirlos en una hoja de cálculo</h2>
<ol><li>Descarga el CSV desde el enlace de arriba.</li><li>En Excel: Datos, luego «Desde el texto/CSV», con el origen UTF-8 y el delimitador «punto y coma». En LibreOffice Calc, ábrelo y elige el juego de caracteres UTF-8 y el separador «punto y coma».</li><li>Comprueba que las tildes se ven bien y que los números con coma se reconocen como números.</li></ol>
<h2>Leerlos con Python</h2>
<p>Sin instalar nada aparte de Python:</p>
<pre><code>{escape(example)}</code></pre>
<h2>Antes de sacar conclusiones</h2>
<ul><li>Un registro de terraza (Madrid) o un recibo de la tasa (València) no prueban que una terraza esté montada ni que un local haya abierto o cerrado.</li>
<li>Las cifras por habitante usan la población empadronada, que no incluye a quienes trabajan o hacen turismo en el barrio.</li>
<li>En València no compares 2023, porque viene incompleto (columna <code>anio_completo</code>), y el índice de vulnerabilidad es de 2021.</li>
<li>Compara cortes del mismo tipo y fíjate en las fechas de cada fuente, que no siempre coinciden.</li></ul>
<h2>Errores y sugerencias</h2>
<p>Si ves un dato que no cuadra o quieres proponer un cruce nuevo, abre una incidencia en <a href="{REPO}/issues">el repositorio</a>, sin datos personales. Las webs: <a href="{MADRID}">Pulso Local Madrid</a> · <a href="{VALENCIA}">Pulso València</a>.</p>
<footer><p><a href="../">Todas las herramientas</a> · <a href="../acerca">Acerca de</a> · <a href="{REPO}">Código abierto (MIT) en GitHub</a></p></footer></main></body></html>'''
    return protect_html(page_metadata(page, canonical=URL, social=True))
