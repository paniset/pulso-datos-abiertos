"""Población por distrito (padrón a 1 de enero) para cruzarla con el registro de terrazas.

Fuente: Ayuntamiento de Madrid, «Población por distrito y barrio a 1 de enero» (CC BY 4.0).
Solo se guardan totales por distrito; el CSV bruto no se persiste. Biblioteca estándar.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from madrid import atomic_write, fetch  # noqa: E402

DATASET = 'https://datos.madrid.es/dataset/300557-0-poblacion-distrito-barrio'
RESOURCE = '300557-0-poblacion-distrito-barrio-csv'
URL = DATASET + '/resource/' + RESOURCE + '/download/' + RESOURCE + '.csv'
DESCRIPTION = 'Población por distrito y barrio a 1 de enero'
DATE_LABEL = '1 de enero de 2026'
DATE = '2026-01-01'
RAW_SHA256 = '86370f0591d5cdad33e7b85b34c26eeac60b87387b8dad908ec63c21c9011835'
RAW_BYTES = 98652
NEIGHBORHOODS = 131
DISTRICTS = 21
OUTPUT = ROOT / 'data' / 'madrid-poblacion-2026.json'


def district_key(name):
    """Nombre del padrón («Chamartín») a la forma del registro de terrazas («CHAMARTIN»)."""
    plain = unicodedata.normalize('NFKD', name.strip()).encode('ascii', 'ignore').decode()
    return ' '.join(plain.upper().split())


# Nombres del censo de terrazas que difieren del padrón (comprobado el 13/11/2026 con el corte de
# octubre de 2026). «SAN ANDRES» es el nombre antiguo del barrio Villaverde Alto-Casco Histórico.
BARRIO_ALIASES = {
    ('VILLA DE VALLECAS', 'CASCO H.VALLECAS'): 'CASCO HISTORICO DE VALLECAS',
    ('VICALVARO', 'CASCO H.VICALVARO'): 'CASCO HISTORICO DE VICALVARO',
    ('BARAJAS', 'CASCO H.BARAJAS'): 'CASCO HISTORICO DE BARAJAS',
    ('VILLAVERDE', 'SAN ANDRES'): 'VILLAVERDE ALTO, CASCO HISTORICO DE VILLAVERDE',
    ('VILLAVERDE', 'LOS ANGELES'): 'ANGELES',
    ('LATINA', 'LAS AGUILAS'): 'AGUILAS',
    ('CIUDAD LINEAL', 'CONCEPCION'): 'LA CONCEPCION',
    ('FUENCARRAL-EL PARDO', 'EL PILAR'): 'PILAR',
    ('FUENCARRAL-EL PARDO', 'PENA GRANDE'): 'PENAGRANDE',
}


def barrio_key(district, barrio):
    """Barrio del censo o del padrón -> «DISTRITO|BARRIO» con el nombre del padrón, sin tildes."""
    d, b = district_key(district), district_key(barrio)
    return f'{d}|{BARRIO_ALIASES.get((d, b), b)}'


def parse_barrios(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';')
    barrios = {}
    for row in reader:
        if row['fecha'].strip() != DATE_LABEL:
            continue
        key = barrio_key(row['distrito'], row['barrio'])
        if key in barrios:
            raise ValueError(f'Padrón: barrio repetido {key}')
        barrios[key] = {'name': ' '.join(row['barrio'].split()), 'population': int(row['num_personas'].strip().replace('.', ''))}
    return dict(sorted(barrios.items()))


def parse(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';')
    needed = {'fecha', 'cod_municipio', 'distrito', 'barrio', 'num_personas'}
    if not needed <= set(reader.fieldnames or []):
        raise ValueError('Padrón: esquema incompatible')
    totals, rows = {}, 0
    for line, row in enumerate(reader, 2):
        if row['fecha'].strip() != DATE_LABEL:
            continue
        if row['cod_municipio'].strip() != '28079':
            raise ValueError(f'Padrón: municipio inesperado en la fila {line}')
        people = row['num_personas'].strip().replace('.', '')
        if not people.isdecimal() or int(people) <= 0:
            raise ValueError(f'Padrón: población inválida en la fila {line}')
        key = district_key(row['distrito'])
        totals[key] = totals.get(key, 0) + int(people)
        rows += 1
    if rows != NEIGHBORHOODS or len(totals) != DISTRICTS:
        raise ValueError(f'Padrón: se esperaban {NEIGHBORHOODS} barrios y {DISTRICTS} distritos ({rows}, {len(totals)})')
    return dict(sorted(totals.items()))


def payload(raw):
    if len(raw) != RAW_BYTES or hashlib.sha256(raw).hexdigest() != RAW_SHA256:
        raise ValueError('Padrón: el CSV publicado ha cambiado; revisión humana necesaria')
    return {'source': payload_source(), 'districts': parse(raw), 'barrios': parse_barrios(raw)}


def load(path=OUTPUT):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = payload_source()
    if data.get('source') != expected or set(data) != {'source', 'districts', 'barrios'}:
        raise ValueError('Padrón saneado: procedencia distinta de la fijada')
    districts = data['districts']
    if (len(districts) != DISTRICTS or not all(type(v) is int and v > 0 for v in districts.values())
            or any(district_key(k) != k for k in districts)):
        raise ValueError('Padrón saneado: distritos inválidos')
    barrios = data['barrios']
    if (len(barrios) != NEIGHBORHOODS or list(barrios) != sorted(barrios)
            or any(not isinstance(v, dict) or set(v) != {'name', 'population'} or type(v['population']) is not int
                   or v['population'] <= 0 or not isinstance(v['name'], str) or not v['name'] for v in barrios.values())
            or any(k.split('|')[0] not in districts for k in barrios)):
        raise ValueError('Padrón saneado: barrios inválidos')
    for district, people in districts.items():
        if sum(v['population'] for k, v in barrios.items() if k.split('|')[0] == district) != people:
            raise ValueError('Padrón saneado: los barrios no suman su distrito')
    return data


def payload_source():
    return {'url': URL, 'dataset': DATASET, 'resource_id': RESOURCE, 'description': DESCRIPTION,
            'date': DATE, 'sha256': RAW_SHA256, 'bytes': RAW_BYTES, 'neighborhoods': NEIGHBORHOODS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    data = payload(fetch(URL))
    atomic_write(args.output, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'districts': len(data['districts']), 'population': sum(data['districts'].values())}))


if __name__ == '__main__':
    main()
