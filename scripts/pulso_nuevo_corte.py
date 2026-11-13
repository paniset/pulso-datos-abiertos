"""Prepara Pulso para comparar los dos últimos cortes mensuales publicados. Biblioteca estándar.

Uso mensual (cuando el Ayuntamiento publica un corte nuevo, hacia el día 1-3):
    python scripts/pulso_nuevo_corte.py            # solo informa: ¿hay corte nuevo?
    python scripts/pulso_nuevo_corte.py --apply    # fija los dos últimos cortes en scripts/madrid.py
Después: python scripts/madrid.py (descarga y valida), python scripts/madrid_serie.py, pruebas y build.
Ver docs/roles/pulso-actualizacion-mensual.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import madrid  # noqa: E402
from madrid_serie import catalog_months  # noqa: E402

MADRID = ROOT / 'scripts' / 'madrid.py'
NAMES = ('RESOURCES', 'PERIODS', 'DATES', 'DESCRIPTIONS', 'LOAD_DATES', 'RAW_HASHES', 'RECORD_HASHES', 'SIZES', 'ROWS', 'URLS')


def pin(period, resource):
    """Valores fijados de un corte, calculados con el mismo analizador estricto que la comparación."""
    raw = madrid.fetch(resource['url'])
    records, quality = madrid.parse_snapshot(raw)
    dates = quality['source_load_dates']
    if len(dates) != 1 or not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}', dates[0]):
        raise ValueError(f'Corte {period}: fecha de carga ausente o múltiple ({dates}); revisión humana necesaria')
    if quality['identical_duplicates']:
        raise ValueError(f'Corte {period}: filas duplicadas; revisión humana necesaria')
    prefix = madrid.DATASET + '/resource/' + resource['resource_id'] + '/download/'
    if not resource['url'].startswith(prefix):
        raise ValueError(f'Corte {period}: URL fuera del recurso municipal')
    day, month, year = dates[0].split('/')
    record_hash = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'RESOURCES': resource['resource_id'], 'PERIODS': period, 'DATES': f'{year}-{month}-{day}',
            'DESCRIPTIONS': resource['description'], 'LOAD_DATES': dates[0], 'RAW_HASHES': hashlib.sha256(raw).hexdigest(),
            'RECORD_HASHES': record_hash, 'SIZES': len(raw), 'ROWS': quality['rows'],
            'URLS': resource['url'][len(prefix):]}


def render(name, values):
    if name == 'URLS':
        items = [f'DATASET + "/resource/" + RESOURCES[{i}] + "/download/{v}"' for i, v in enumerate(values)]
        return 'URLS = (' + ',\n        '.join(items) + ')\n'
    items = [json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v) for v in values]
    joined = ', '.join(items)
    if len(name) + len(joined) > 100:
        joined = (',\n' + ' ' * (len(name) + 4)).join(items)
    return f'{name} = ({joined})\n'


def rewrite(source, pins):
    for name in NAMES:
        pattern = re.compile(rf'^{name} = \(.*?\)\n', re.S | re.M)
        if len(pattern.findall(source)) != 1:
            raise ValueError(f'No se encuentra una única asignación de {name} en madrid.py')
        block = render(name, [p[name] for p in pins])
        source = pattern.sub(lambda _: block, source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    catalog = json.loads(madrid.fetch(madrid.API))['result']
    months = catalog_months(catalog)
    latest = list(months)[-2:]
    current = list(madrid.PERIODS)
    print(json.dumps({'actual': current, 'ultimos_publicados': latest, 'nuevo': latest != current}, ensure_ascii=False))
    if not args.apply or latest == current:
        return
    pins = [pin(period, months[period]) for period in latest]
    MADRID.write_text(rewrite(MADRID.read_text(encoding='utf-8'), pins), encoding='utf-8')
    print('madrid.py actualizado:', ', '.join(f'{p["PERIODS"]} ({p["ROWS"]} terrazas)' for p in pins))


if __name__ == '__main__':
    main()
