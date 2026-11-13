import json
import unittest

from scripts import madrid_serie as ms

HEADER = 'id_terraza;id_local;desc_distrito_local;fx_carga;desc_barrio_local\r\n'


def raw(rows):
    return ('\ufeff' + HEADER + ''.join(';'.join(r + ['SOL']) + '\r\n' for r in rows)).encode('utf-8')


class SerieTests(unittest.TestCase):
    def test_summarize_counts_unique_ids_and_rows_without_district(self):
        data = ms.summarize('2025-01', {'resource_id': 'r', 'url': 'u', 'description': 'd'}, raw([
            ['1', '9', 'CENTRO', '2025-01-31 03:30:20.1'], ['1', '9', 'CENTRO', '2025-01-31 03:30:20.1'],
            ['2', '9', ' Retiro ', '31/01/2025'], ['3', '9', '', '']]))
        self.assertEqual((data['total'], data['rows']), (3, 4))
        self.assertEqual(data['districts'], {'CENTRO': 1, 'RETIRO': 1, ms.NO_DISTRICT: 1})
        self.assertEqual(data['load_dates'], ['2025-01-31'])

    def test_summarize_rejects_bad_input(self):
        res = {'resource_id': 'r', 'url': 'u', 'description': 'd'}
        for rows in ([['x', '9', 'CENTRO', '']], [['1', '9', 'CENTRO', ''], ['1', '9', 'RETIRO', '']], []):
            with self.assertRaises(ValueError):
                ms.summarize('2025-01', res, raw(rows))

    def test_catalog_filters_months_and_rejects_duplicates(self):
        base = ms.DATASET + '/resource/{0}/download/{0}.csv'
        catalog = {'resources': [
            {'id': 'a', 'format': 'CSV', 'description': 'Terrazas. Octubre 2024', 'url': base.format('a')},
            {'id': 'b', 'format': 'JSON', 'description': 'Terrazas. Noviembre 2024', 'url': base.format('b')},
            {'id': 'c', 'format': 'CSV', 'description': 'Terrazas. Septiembre 2024', 'url': base.format('c')},
            {'id': 'd', 'format': 'CSV', 'description': 'Locales. Octubre 2024', 'url': base.format('d')}]}
        self.assertEqual(list(ms.catalog_months(catalog)), ['2024-10'])
        catalog['resources'].append({'id': 'e', 'format': 'CSV', 'description': 'Terrazas. Octubre 2024', 'url': base.format('e')})
        with self.assertRaises(ValueError):
            ms.catalog_months(catalog)

    def test_saved_series_is_valid_and_tampering_is_rejected(self):
        data = ms.load()
        self.assertGreaterEqual(len(data['months']), 2)
        for mutate in (lambda d: d['months'][0].__setitem__('total', 1),
                       lambda d: d['months'].reverse(),
                       lambda d: d.__setitem__('license', 'otra')):
            tampered = json.loads(json.dumps(data))
            mutate(tampered)
            with self.assertRaises(ValueError):
                ms.validate_series(tampered)

    def test_update_refuses_changed_month(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        url = ms.DATASET + '/resource/a/download/a.csv'
        catalog = {'license_id': 'cc-by', 'resources': [{'id': 'a', 'format': 'CSV', 'description': 'Terrazas. Octubre 2024', 'url': url}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 's.json'
            with patch.object(ms, 'fetch', return_value=raw([['1', '9', 'CENTRO', '']])):
                ms.update(path, catalog)
            with patch.object(ms, 'fetch', return_value=raw([['1', '9', 'CENTRO', ''], ['2', '9', 'CENTRO', '']])):
                ms.update(path, catalog)  # sin --verify no se vuelve a descargar
                with self.assertRaises(ValueError):
                    ms.update(path, catalog, verify=True)


if __name__ == '__main__':
    unittest.main()
