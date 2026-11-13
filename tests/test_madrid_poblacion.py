import json
from pathlib import Path
import tempfile
import unittest

from scripts import madrid_poblacion as mp

ROOT = Path(__file__).resolve().parents[1]
HEADER = 'fecha;cod_municipio;municipio;cod_distrito;distrito;cod_barrio;barrio;num_personas;num_personas_hombres;num_personas_mujeres\r\n'


def csv_bytes(rows):
    return ('﻿' + HEADER + ''.join(';'.join(row) + '\r\n' for row in rows)).encode('utf-8')


class PoblacionTests(unittest.TestCase):
    def test_district_key_matches_register_names(self):
        self.assertEqual(mp.district_key(' Chamartín'), 'CHAMARTIN')
        self.assertEqual(mp.district_key('Fuencarral-El Pardo'), 'FUENCARRAL-EL PARDO')
        self.assertEqual(mp.district_key('Vicálvaro'), 'VICALVARO')

    def test_parse_sums_neighborhoods_of_the_pinned_year_only(self):
        rows = []
        for d in range(mp.DISTRICTS):
            for b in range(mp.NEIGHBORHOODS // mp.DISTRICTS + (1 if d < mp.NEIGHBORHOODS % mp.DISTRICTS else 0)):
                rows.append([mp.DATE_LABEL, '28079', 'Madrid', str(d), f'Distrito {d:02}', f'{d}{b}', 'B', '1.000', '500', '500'])
                rows.append(['1 de enero de 2025', '28079', 'Madrid', str(d), f'Distrito {d:02}', f'{d}{b}', 'B', '9.999', '1', '1'])
        totals = mp.parse(csv_bytes(rows))
        self.assertEqual(len(totals), mp.DISTRICTS)
        self.assertEqual(sum(totals.values()), 1000 * mp.NEIGHBORHOODS)

    def test_parse_rejects_wrong_shape_and_values(self):
        with self.assertRaises(ValueError):
            mp.parse(csv_bytes([[mp.DATE_LABEL, '28079', 'Madrid', '1', 'Centro', '11', 'Palacio', '23.410', '1', '1']]))
        with self.assertRaises(ValueError):
            mp.parse(csv_bytes([[mp.DATE_LABEL, '28079', 'Madrid', '1', 'Centro', '11', 'Palacio', '-5', '1', '1']]))
        with self.assertRaises(ValueError):
            mp.parse(b'a;b\r\n1;2\r\n')

    def test_payload_requires_pinned_bytes(self):
        with self.assertRaises(ValueError):
            mp.payload(b'x' * mp.RAW_BYTES)

    def test_saved_file_loads_and_tampering_is_rejected(self):
        data = mp.load()
        self.assertEqual(sum(data['districts'].values()), 3497277)
        for mutate in (lambda d: d['source'].__setitem__('sha256', '0' * 64),
                       lambda d: d['districts'].pop('CENTRO'),
                       lambda d: d['districts'].__setitem__('CENTRO', 0),
                       lambda d: d.__setitem__('extra', 1)):
            tampered = json.loads(json.dumps(data))
            mutate(tampered)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'p.json'
                path.write_text(json.dumps(tampered), encoding='utf-8')
                with self.assertRaises(ValueError):
                    mp.load(path)


if __name__ == '__main__':
    unittest.main()
