import csv
import io
import json
import re
import unittest

from scripts import pulso_valencia as pv

HEADER = ('Periodo;Distrito;Barrio;geo_shape;geo_point_2d;Codigo Distrito;Codigo Barrio;Numero Recibos personalidad fisica;'
          'Numero Recibos personalidad juridica;Numero Recibos sin personalidad;Numero recibos zona 1;Numero recibos zona 2;'
          'Numero recibos zona 3;Numero Recibos totales;Importe recibos personalidad fisica;Importe recibos personalidad juridca;'
          'Importe recibos sin personalidad;Importe recibos Zona 1;Importe recibos Zona 2;Importe recibos Zona 3;Importe recibos totales\r\n')


def raw(rows):
    lines = [f'{y};{d};{b};;;1;1;{f};{j};0;___;___;___;{t};0;0;0;___;___;___;{imp}' for y, d, b, f, j, t, imp in rows]
    return ('﻿' + HEADER + '\r\n'.join(lines) + '\r\n').encode('utf-8')


class ParseTests(unittest.TestCase):
    def test_parse_aggregates_and_flags_incomplete_years(self):
        data = pv.parse(raw([('2024', 'CIUTAT VELLA', 'SANT FRANCESC', 3, 2, 5, '100.5'),
                             ('2024', 'EXTRAMURS', 'ARRANCAPINS', 1, 1, 2, '10'),
                             ('2025', 'CIUTAT VELLA', 'SANT FRANCESC', 2, 2, 5, '90')]))
        self.assertTrue(data['2024']['complete'])
        self.assertFalse(data['2025']['complete'])
        self.assertEqual(data['2024']['districts']['CIUTAT VELLA']['recibos'], 5)
        self.assertEqual(data['2025']['mismatch'], 1)
        self.assertEqual(data['2025']['barrios']['CIUTAT VELLA|SANT FRANCESC']['recibos'], 5)

    def test_parse_rejects_bad_rows(self):
        for rows in ([('20x4', 'A', 'B', 1, 0, 1, '1')], [('2024', 'A', 'B', 1, 0, 1, '-3')],
                     [('2024', 'A', 'B', 'x', 0, 1, '1')],
                     [('2024', 'A', 'B', 1, 0, 1, '1'), ('2024', 'A', 'B', 1, 0, 1, '1')]):
            with self.assertRaises(ValueError):
                pv.parse(raw(rows))

    def test_fetch_only_official_host(self):
        with self.assertRaises(ValueError):
            pv.fetch('https://example.com/x.csv')

    def test_names(self):
        self.assertEqual(pv.nice("POBLES DE L'OEST"), "Pobles de l'Oest")
        self.assertEqual(pv.nice('ALGIROS'), 'Algirós')
        self.assertEqual(pv.nice('EL CABANYAL-EL CANYAMELAR'), 'El Cabanyal-El Canyamelar')


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = pv.load()
        cls.page = pv.render(cls.data)
        cls.csv = pv.render_csv(cls.data)

    def test_saved_data_is_consistent(self):
        years = self.data['years']
        self.assertEqual([y for y, v in years.items() if not v['complete']], ['2023'])
        for value in years.values():
            self.assertEqual(sum(d['recibos'] for d in value['districts'].values()),
                             sum(b['recibos'] for b in value['barrios'].values()))

    def test_page_metadata_csp_and_privacy(self):
        self.assertIn('<link rel="canonical" href="https://paniset.github.io/pulso-valencia/">', self.page)
        self.assertIn('content="index,follow"', self.page)
        self.assertIn('Content-Security-Policy', self.page)
        self.assertEqual(self.page.count('<h1>'), 1)
        self.assertNotRegex(self.page, r'\son[a-z]+=|style=|<style')
        self.assertTrue(all('ld+json' in m for m in re.findall(r'<script([^>]*)>', self.page)))
        self.assertNotIn('fisica', self.csv.lower())
        self.assertIn('no terrazas en funcionamiento', self.page)
        self.assertIn('2023', self.page)

    def test_figures_match_data(self):
        years = self.data['years']
        last = max(y for y, v in years.items() if v['complete'])
        total = sum(d['recibos'] for d in years[last]['districts'].values())
        self.assertIn(f'{pv.es_int(total)} en {last}', self.page)
        rows = list(csv.reader(io.StringIO(self.csv.lstrip('﻿')), delimiter=';'))
        self.assertEqual(sum(int(r[4]) for r in rows[1:] if r[0] == last), total)
        dataset = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', self.page, re.S).group(1))
        self.assertEqual(dataset['isBasedOn'], [pv.DATASET, pv.VULN_DATASET])

    def test_vulnerability_join_by_code(self):
        years, vuln = self.data['years'], self.data['vulnerabilidad']['barrios']
        self.assertEqual(len(vuln), 70)
        last = max(y for y, v in years.items() if v['complete'])
        codes = {b['codigo'] for b in years[last]['barrios'].values()}
        self.assertEqual(len(codes), len(years[last]['barrios']))
        self.assertLessEqual(set(vuln), codes)  # los 70 barrios con índice tienen recibos y casan por código
        outside = [b for b in years[last]['barrios'].values() if b['codigo'] not in vuln]
        self.assertTrue(all(int(b['codigo'][:2]) >= 17 for b in outside))  # solo pedanías sin índice
        self.assertIn('no una relación de causa', self.page)
        self.assertEqual(pv.barrio_code('03', '4'), '34')
        with self.assertRaises(ValueError):
            pv.barrio_code('1', '12')

    def test_generated_files_match(self):
        self.assertEqual((pv.OUT / 'index.html').read_text(encoding='utf-8'), self.page)


if __name__ == '__main__':
    unittest.main()
