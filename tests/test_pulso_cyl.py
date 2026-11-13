import csv
import io
import json
import re
import unittest

from scripts import pulso_cyl as pc


def table(province_code, rows):
    out = [{'Nombre': 'Prov. Total. Total habitantes. Personas. ', 'MetaData': [{'Codigo': province_code}], 'Data': [{'Anyo': pc.POPULATION_YEAR, 'Valor': 1}]}]
    for code, name, people in rows:
        out.append({'Nombre': f'{name}. Total. Total habitantes. Personas. ', 'MetaData': [{'Codigo': code, 'Nombre': name}],
                    'Data': [{'Anyo': pc.POPULATION_YEAR, 'Valor': people}]})
        out.append({'Nombre': f'{name}. Hombres. Total habitantes. Personas. ', 'MetaData': [{'Codigo': code, 'Nombre': name}],
                    'Data': [{'Anyo': pc.POPULATION_YEAR, 'Valor': 0}]})
    return out


class NamesTests(unittest.TestCase):
    def test_article_formats_match(self):
        self.assertEqual(pc.key('Barraco (El)'), pc.key('Barraco, El'))
        self.assertEqual(pc.key('Barraco, El'), 'EL BARRACO')
        self.assertEqual(pc.key('Ávila'), 'AVILA')
        self.assertEqual(pc.key('Bañeza, La'), 'LA BANEZA')

    def test_fetch_only_official_hosts(self):
        with self.assertRaises(ValueError):
            pc.fetch('https://example.com/x', pc.JCYL)
        with self.assertRaises(ValueError):
            pc.fetch('http://analisis.datosabiertos.jcyl.es/x', pc.JCYL)


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.population = {'05001': {'nombre': 'Adanero', 'provincia': 'Ávila', 'habitantes': 200},
                           '05020': {'nombre': 'Barraco, El', 'provincia': 'Ávila', 'habitantes': 1800},
                           '05119': {'nombre': 'Manjabálago y Ortigosa de Rioalmar', 'provincia': 'Ávila', 'habitantes': 50}}

    def test_registry_counts_only_hosteleria_and_uses_aliases(self):
        raw = ('﻿establecimiento;provincia;municipio\r\n'
               'Bares;Ávila;Barraco (El)\r\nRestaurantes;Ávila;Barraco (El)\r\n'
               'Cafeterías;Ávila;Manjabálago\r\nAlojam. Turismo Rural;Ávila;Adanero\r\n'
               'Bares;Asturias;Somiedo\r\nBares;Ávila;\r\nBares;Ávila;Inventado\r\n').encode('utf-8')
        counts, other = pc.parse_registry(raw, self.population)
        self.assertEqual(counts['05020'], {'bares': 1, 'restaurantes': 1, 'cafeterias': 0})
        self.assertEqual(counts['05119']['cafeterias'], 1)
        self.assertEqual(pc.total(counts['05001'] | {}), 0)
        self.assertEqual((other['fuera_de_la_comunidad'], other['sin_municipio'], other['sin_equivalencia']), (1, 1, 1))

    def test_registry_rejects_personal_columns(self):
        raw = '﻿establecimiento;provincia;municipio;telefono_1\r\nBares;Ávila;Adanero;600000000\r\n'.encode('utf-8')
        with self.assertRaises(ValueError):
            pc.parse_registry(raw, self.population)

    def test_population_requires_every_municipality(self):
        tables = {code: table(code, []) for code in pc.PROVINCES}
        tables['05'] = table('05', [('05001', 'Adanero', 200)])
        with self.assertRaises(ValueError):
            pc.parse_population(tables)


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = pc.load()
        cls.page = pc.render(cls.data)
        cls.csv = pc.render_csv(cls.data)

    def test_saved_data(self):
        munis = self.data['municipios']
        self.assertEqual(len(munis), 2248)
        self.assertEqual(self.data['registry']['sin_equivalencia'], 0)
        self.assertGreater(sum(m['habitantes'] for m in munis.values()), 2_000_000)

    def test_page_figures_and_csp(self):
        munis = self.data['municipios']
        without = sum(1 for m in munis.values() if pc.total(m) == 0)
        self.assertIn(f'{pc.es_int(without)} municipios sin ninguno', self.page)
        self.assertIn('<link rel="canonical" href="https://paniset.github.io/pulso-castilla-y-leon/">', self.page)
        self.assertIn('content="index,follow"', self.page)
        self.assertEqual(self.page.count('<h1>'), 1)
        self.assertNotRegex(self.page, r'\son[a-z]+=|style=|<style')
        self.assertTrue(all('ld+json' in m for m in re.findall(r'<script([^>]*)>', self.page)))
        self.assertIn('no locales abiertos', self.page)

    def test_csv_matches_and_has_no_personal_fields(self):
        rows = list(csv.reader(io.StringIO(self.csv.lstrip('﻿')), delimiter=';'))
        self.assertEqual(len(rows), 2249)
        self.assertNotIn('telefono', rows[0])
        self.assertNotIn('email', rows[0])
        self.assertEqual(sum(int(r[4]) for r in rows[1:]), sum(m['bares'] for m in self.data['municipios'].values()))
        self.assertNotRegex(self.csv, r'@|\b6\d{8}\b')

    def test_generated_files_match(self):
        self.assertEqual((pc.OUT / 'index.html').read_text(encoding='utf-8'), self.page)


if __name__ == '__main__':
    unittest.main()
