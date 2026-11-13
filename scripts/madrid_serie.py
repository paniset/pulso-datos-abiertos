"""Serie mensual de terrazas registradas en Madrid (total y por distrito). Biblioteca estándar.

Lee del catálogo de datos.madrid.es los CSV «Terrazas. <Mes> <Año>» desde START, los analiza con el
mismo validador que la comparación (scripts/madrid.py) y guarda solo recuentos agregados. Cada mes
queda fijado por recurso, tamaño y SHA-256; con --verify se vuelven a descargar los meses guardados y,
si el Ayuntamiento ha cambiado alguno, el proceso se detiene en lugar de reescribir la serie.
Los CSV brutos no se persisten.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import math
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from madrid import API, DATASET, atomic_write, fetch, validate_url  # noqa: E402

START = '2024-10'
OUTPUT = ROOT / 'data' / 'madrid-terrazas-serie.json'
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre']
DESCRIPTION = re.compile(r'Terrazas\. (' + '|'.join(MONTHS) + r') (\d{4})', re.I)


def catalog_months(catalog):
    """{'AAAA-MM': recurso CSV} para los cortes mensuales de terrazas desde START."""
    found = {}
    for resource in catalog['resources']:
        match = DESCRIPTION.fullmatch((resource.get('description') or '').strip())
        if not match or (resource.get('format') or '').upper() != 'CSV':
            continue
        period = f'{match.group(2)}-{MONTHS.index(match.group(1).lower()) + 1:02}'
        if period < START:
            continue
        if period in found:
            raise ValueError(f'Dos CSV para el mismo mes {period}: revisión humana necesaria')
        validate_url(resource['url'])
        found[period] = {'resource_id': resource['id'], 'url': resource['url'],
                         'description': resource['description'].strip()}
    return dict(sorted(found.items()))


NO_DISTRICT = 'SIN DISTRITO'


def load_date(value):
    """«2024-10-31 03:30:20» o «17/05/2026» -> «2024-10-31»; vacío si no se reconoce."""
    value = value.strip()
    if re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return value[:10]
    match = re.fullmatch(r'([0-9]{2})/([0-9]{2})/([0-9]{4})', value)
    return f'{match.group(3)}-{match.group(2)}-{match.group(1)}' if match else ''


CAPACITY_FIELDS = ('Superficie_ES', 'Superficie_RA', 'sillas_es', 'sillas_ra', 'desc_periodo_terraza')


def number(value):
    """«16.70», «16,70» o vacío -> float (vacío = 0). Rechaza negativos, infinitos y texto.
    Las sillas se truncan a entero al sumarlas (en origen son enteros)."""
    text = (value or '').strip().replace(',', '.')
    if not text:
        return 0.0
    result = float(text)
    if result < 0 or not math.isfinite(result):
        raise ValueError(f'Valor numérico inválido: {value!r}')
    return result


def summarize(period, resource, raw):
    """Recuento por distrito de identificadores de terraza únicos. Más tolerante que la comparación:
    los cortes antiguos traen algunas filas sin distrito, que se cuentan aparte."""
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';')
    if not {'id_terraza', 'desc_distrito_local', 'desc_barrio_local'} <= set(reader.fieldnames or []):
        raise ValueError(f'Corte {period}: esquema incompatible')
    from madrid_poblacion import barrio_key
    seen, districts, barrios, dates, rows = {}, Counter(), Counter(), set(), 0
    has_capacity = set(CAPACITY_FIELDS) <= set(reader.fieldnames or [])
    capacity = {}
    for line, row in enumerate(reader, 2):
        if None in row:
            raise ValueError(f'Corte {period}: fila con campos extra ({line})')
        key = (row['id_terraza'] or '').strip()
        if not key.isdecimal():
            raise ValueError(f'Corte {period}: identificador inválido ({line})')
        district = ' '.join((row['desc_distrito_local'] or '').split()).upper() or NO_DISTRICT
        rows += 1
        if key in seen:
            if seen[key] != district:
                raise ValueError(f'Corte {period}: terraza {key} repetida en dos distritos')
            continue
        seen[key] = district
        districts[district] += 1
        barrio = (row['desc_barrio_local'] or '').strip()
        if district != NO_DISTRICT and barrio:
            barrios[barrio_key(district, barrio)] += 1
        if has_capacity:
            item = capacity.setdefault(district, {'m2_es': 0.0, 'm2_ra': 0.0, 'sillas_es': 0, 'sillas_ra': 0, 'anuales': 0})
            item['m2_es'] += number(row['Superficie_ES'])
            item['m2_ra'] += number(row['Superficie_RA'])
            item['sillas_es'] += int(number(row['sillas_es']))
            item['sillas_ra'] += int(number(row['sillas_ra']))
            item['anuales'] += row['desc_periodo_terraza'].strip().lower() == "anual"
        if row.get('fx_carga'):
            dates.add(load_date(row['fx_carga']))
    if not seen:
        raise ValueError(f'Corte {period}: vacío')
    return {'period': period, **resource, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'rows': rows, 'load_dates': sorted(d for d in dates if d),
            'total': len(seen), 'districts': dict(sorted(districts.items())), 'barrios': dict(sorted(barrios.items())),
            'capacity': {name: {**v, 'm2_es': round(v['m2_es']), 'm2_ra': round(v['m2_ra'])}
                         for name, v in sorted(capacity.items())} if has_capacity else None}


def validate_series(data):
    if set(data) != {'source_url', 'license', 'months'} or data['source_url'] != DATASET or data['license'] != 'CC BY 4.0':
        raise ValueError('Serie: cabecera inválida')
    periods = [month['period'] for month in data['months']]
    if periods != sorted(set(periods)) or not periods or periods[0] < START:
        raise ValueError('Serie: meses duplicados o desordenados')
    for month in data['months']:
        if (not re.fullmatch(r'[0-9]{4}-[0-9]{2}', month['period']) or not re.fullmatch(r'[a-f0-9]{64}', month['sha256'])
                or not month['url'].startswith(DATASET + '/resource/' + month['resource_id'] + '/download/')
                or sum(month['districts'].values()) != month['total'] or month['total'] <= 0
                or not isinstance(month.get('barrios'), dict)):
            raise ValueError(f'Serie: mes {month.get("period")} incoherente')
    return data


def load(path=OUTPUT):
    return validate_series(json.loads(Path(path).read_text(encoding='utf-8')))


def update(path=OUTPUT, catalog=None, verify=False):
    """Añade los meses nuevos del catálogo; los ya guardados deben seguir siendo idénticos."""
    catalog = catalog or json.loads(fetch(API))['result']
    if catalog.get('license_id') != 'cc-by':
        raise ValueError('Licencia cambiada: revisión humana necesaria')
    current = {month['period']: month for month in load(path)['months']} if Path(path).exists() else {}
    months = []
    for period, resource in catalog_months(catalog).items():
        known = current.get(period)
        if known and not verify and {k: known[k] for k in resource} == resource:
            months.append(known)  # ya incorporado: no se vuelve a descargar
            continue
        summary = summarize(period, resource, fetch(resource['url']))
        if known and known != summary:
            raise ValueError(f'El corte {period} ha cambiado desde que se incorporó; no se sobrescribe')
        months.append(summary)
    missing = set(current) - {month['period'] for month in months}
    if missing:
        raise ValueError('Han desaparecido del catálogo meses ya incorporados: ' + ', '.join(sorted(missing)))
    data = validate_series({'source_url': DATASET, 'license': 'CC BY 4.0', 'months': months})
    atomic_write(Path(path), json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    return data, sorted(set(m['period'] for m in months) - set(current))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--verify', action='store_true', help='Volver a descargar y comparar los meses ya guardados')
    args = parser.parse_args()
    data, added = update(args.output, verify=args.verify)
    print(json.dumps({'months': len(data['months']), 'added': added,
                      'last': data['months'][-1]['period']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
