import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from collections import Counter
from scripts.pulso_sample import ROOT, FIELDS, CSS, escape, csv_safe, generate, render_csv, render_html


class PulsoSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'data/radar.json').read_bytes()
        cls.data = json.loads(cls.raw)
        cls.digest = hashlib.sha256(cls.raw).hexdigest()

    def test_counts_and_complete_fidelity(self):
        rows = list(csv.DictReader(io.StringIO(render_csv(self.data, self.digest).lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(len(rows), 60)
        self.assertEqual(Counter(r['type'] for r in rows), {'entrada':29,'salida':11,'cambio_estado':20})
        for actual, expected in zip(rows, self.data['changes']):
            for key in FIELDS:
                value = ', '.join(expected[key]) if key == 'changed_fields' else expected.get(key)
                self.assertEqual(actual[key], '' if value is None else str(value))
            self.assertEqual(actual['radar_sha256'], self.digest)
            self.assertEqual(actual['from_date'], self.data['meta']['from_date'])
            self.assertEqual(actual['to_date'], self.data['meta']['to_date'])

    def test_html_records_summary_and_traceability(self):
        report = render_html(self.data, self.digest)
        self.assertEqual(report.count('<article class="record"'), 60)
        for item in self.data['changes']:
            self.assertIn(f'id="terraza-{item["id"]}"', report)
            self.assertIn(escape(item['before']), report)
            self.assertIn(escape(item['after']), report)
        for district, count in Counter(i['district'] for i in self.data['changes']).items():
            fragment = report.split('<th scope="row">' + district + '</th>')[1].split('</tr>')[0]
            self.assertTrue(fragment.endswith(f'<td>{count}</td>'))
        for source in self.data['meta']['sources']:
            self.assertIn(source['sha256'], report)
        self.assertIn(self.digest, report)
        self.assertIn('CC BY 4.0', report)
        self.assertIn('no apertura o cierre confirmado', report)

    def test_csv_formula_neutralization_and_quoting(self):
        for value in ['=1+1','+CMD','-1','@SUM(A1)','  =1','\t=1','\rtext','\ntext']:
            self.assertTrue(csv_safe(value).startswith("'"))
        data = json.loads(self.raw)
        data['changes'][0]['district'] = '=HYPERLINK("x");\nOtra línea'
        rows = list(csv.DictReader(io.StringIO(render_csv(data, self.digest).lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(rows[0]['district'], "'" + data['changes'][0]['district'])
        self.assertEqual(len(rows),60)

    def test_html_escaping(self):
        data = json.loads(self.raw)
        data['changes'][0]['before'] = '<script>alert("x")</script>&'
        report = render_html(data, self.digest)
        self.assertNotIn('<script>', report)
        self.assertIn('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;', report)

    def test_generation_and_rejection_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            self.assertEqual(generate(output=output), self.digest)
            self.assertEqual((output/'index.html').read_text(encoding='utf-8'),render_html(self.data,self.digest))
            self.assertEqual((output/'muestra.css').read_text(encoding='utf-8'),CSS)
            self.assertEqual((output/'pulso-muestra.csv').read_bytes(),render_csv(self.data,self.digest).encode('utf-8'))
            data = json.loads(self.raw)
            data['changes'][0]['email'] = 'inventado@example.com'
            source = Path(directory)/'invalid.json'
            source.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError):
                generate(source, Path(directory)/'rejected')
            self.assertFalse((Path(directory)/'rejected').exists())


if __name__ == '__main__':
    unittest.main()
