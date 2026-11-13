import copy
import json
from pathlib import Path
import unittest

from factory.radar_schema import validate_radar


class RadarSchemaTests(unittest.TestCase):
    def setUp(self):
        self.real = json.loads((Path(__file__).resolve().parents[1]/'data/radar.json').read_text(encoding='utf-8'))

    def assert_invalid(self, mutate):
        payload = copy.deepcopy(self.real)
        mutate(payload)
        with self.assertRaises(ValueError):
            validate_radar(payload)

    def test_real_current_artifact_valid(self):
        self.assertIs(validate_radar(self.real), self.real)

    def test_synthetic_is_not_fixed_to_madrid_dates_or_numeric_ids(self):
        payload = {'meta': {'source_url': 'https://example.org/demo', 'from_date': '2018-02-01',
                   'to_date': '2018-03-01', 'generated_at': '2018-03-02T00:00:00Z', 'mode': 'synthetic',
                   'total_changes': 1, 'displayed_changes': 1, 'counts': {'entrada': 1}, 'sources': [],
                   'coverage_note': 'Ejemplo sintético'}, 'changes': [
                   {'id': 'demo-1', 'local_id': 'local-a', 'district': 'Ejemplo', 'neighborhood': 'Ejemplo',
                    'activity': 'Ejemplo', 'type': 'entrada', 'before': None, 'after': 'Estado de ejemplo', 'changed_fields': []}]}
        validate_radar(payload)

    def test_changes_scalar_null_or_missing_rejected(self):
        for value in (1, None, {}, 'records'):
            self.assert_invalid(lambda p: p.update(changes=value))
        self.assert_invalid(lambda p: p.pop('changes'))

    def test_invalid_dates_order_future_and_generation(self):
        for key, value in (('from_date','2026-02-30'),('to_date','9999-01-01'),
                           ('from_date','2026-10-31'),('to_date','2026-01-01'),
                           ('generated_at','2026-11-08'),('generated_at','9999-01-01T00:00:00Z')):
            self.assert_invalid(lambda p: p['meta'].update({key:value}))

    def test_counts_and_display_must_match(self):
        for key, value in (('displayed_changes', 59), ('total_changes', 59), ('total_changes', True),
                           ('counts', {'entrada': 60}), ('counts', {'inventado':60})):
            self.assert_invalid(lambda p: p['meta'].update({key:value}))

    def test_unique_ids_and_allowlist(self):
        self.assert_invalid(lambda p: p['changes'][1].update(id=p['changes'][0]['id']))
        self.assert_invalid(lambda p: p['changes'][0].update(telefono='123456789'))
        self.assert_invalid(lambda p: p['meta'].update(customer_email='x@example.org'))
        self.assert_invalid(lambda p: p['changes'][0].update(district='persona@example.org'))

    def test_before_after_type_consistency(self):
        self.assert_invalid(lambda p: p['changes'][0].update(after=None))
        self.assert_invalid(lambda p: p['changes'][0].update(before='Ya existía'))
        self.assert_invalid(lambda p: p['changes'][0].update(after={'bad':'type'}))
        self.assert_invalid(lambda p: p['changes'][0].update(type='apertura_confirmada'))
        self.assert_invalid(lambda p: p['changes'][0].update(changed_fields=['telefono']))

    def test_sources_host_period_hash_and_bytes(self):
        for key, value in (('url','http://datos.madrid.es/a'),('url','https://evil.test/a'),
                           ('url','https://user:pass@datos.madrid.es/a'),('period','2020-01'),
                           ('sha256','no-hash'),('bytes',-1),('bytes',True)):
            self.assert_invalid(lambda p: p['meta']['sources'][0].update({key:value}))
        self.assert_invalid(lambda p: p['meta'].update(source_url='https://example.com'))
        self.assert_invalid(lambda p: p['meta'].update(sources=[]))

    def test_source_quality_and_net_change_balance(self):
        self.assert_invalid(lambda p: p['meta']['sources'][0]['quality'].update(source_load_dates=['01/01/2020']))
        self.assert_invalid(lambda p: p['meta']['sources'][0]['quality'].update(rows=1))
        self.assert_invalid(lambda p: p['meta']['sources'][0]['quality'].update(rows=6595,unique_ids=6595))


if __name__ == '__main__':
    unittest.main()
