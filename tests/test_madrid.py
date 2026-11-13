import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
from scripts.madrid import (REQUIRED, RESOURCES, PERIODS, URLS, DESCRIPTIONS, SIZES,
                           OfficialRedirectHandler, build, compare, download_snapshot,
                           fetch, parse_snapshot, validate_payload)


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=sorted(REQUIRED) + ["rotulo", "telefono", "fx_carga"], delimiter=";")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")


def row(key="1", status="Abierto"):
    return {"id_terraza": key, "id_local": "123", "desc_distrito_local": "CENTRO ",
            "desc_barrio_local": "SOL", "desc_situacion_local": status,
            "desc_situacion_terraza": "Abierta", "desc_periodo_terraza": "Anual",
            "rotulo": "PERSONAL DATA MUST NOT BE EXPORTED", "telefono": "123456789"}


def payload(index):
    path = Path(__file__).resolve().parents[1] / "data" / f"madrid-terrazas-{PERIODS[index]}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def catalog():
    return {"license_id": "cc-by", "resources": [
        {"id": RESOURCES[i], "url": URLS[i], "description": DESCRIPTIONS[i],
         "format": "CSV", "size": SIZES[i]} for i in range(2)]}


class MadridTests(unittest.TestCase):
    def test_allowlist_and_whitespace(self):
        records, _ = parse_snapshot(csv_bytes([row()]))
        self.assertEqual(records["1"]["district"], "CENTRO")
        self.assertNotIn("PERSONAL DATA", str(records))
        self.assertNotIn("telefono", str(records))

    def test_identical_duplicates_counted(self):
        records, quality = parse_snapshot(csv_bytes([row(), row()]))
        self.assertEqual(len(records), 1)
        self.assertEqual(quality["identical_duplicates"], 1)

    def test_conflicting_duplicates_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicada"):
            parse_snapshot(csv_bytes([row(), row(status="Cerrado")]))

    def test_schema_change_fails(self):
        with self.assertRaisesRegex(ValueError, "Esquema"):
            parse_snapshot(b"id;nombre\n1;x\n")

    def test_missing_id_fails(self):
        with self.assertRaisesRegex(ValueError, "Identificador"):
            parse_snapshot(csv_bytes([row(key="")]))

    def test_empty_snapshot_fails(self):
        with self.assertRaisesRegex(ValueError, "vacío"):
            parse_snapshot(csv_bytes([]))

    def test_comparison_is_not_opening_inference(self):
        before, _ = parse_snapshot(csv_bytes([row(), row("3")]))
        after, _ = parse_snapshot(csv_bytes([row(status="Cerrado"), row("2")]))
        changes = compare(before, after)
        self.assertEqual([change["type"] for change in changes], ["cambio_estado", "entrada", "salida"])
        self.assertIsNone(changes[1]["before"])
        self.assertIsNone(changes[2]["after"])
        self.assertEqual(changes[0]["changed_fields"], ["local_status"])

    def test_unchanged_has_no_changes(self):
        records, _ = parse_snapshot(csv_bytes([row()]))
        self.assertEqual(compare(records, records), [])

    def test_url_restricted_before_network(self):
        for url in ("http://datos.madrid.es/a", "https://example.com/a", "file:///tmp/a",
                    "https://datos.madrid.es:8443/a", "https://user@datos.madrid.es/a"):
            with self.assertRaises(ValueError):
                fetch(url)

    def test_csv_wrong_or_missing_date_rejected(self):
        for date in ("01/01/2020", "31/10/2026", ""):
            record = row()
            record["fx_carga"] = date
            with self.assertRaisesRegex(ValueError, "Fecha"):
                parse_snapshot(csv_bytes([record]), expected_date="30/09/2026")

    def test_false_catalog_month_rejected_before_download(self):
        source = catalog()
        source["resources"][0]["description"] = "Terrazas. Enero 2020"
        with patch("scripts.madrid.fetch") as network:
            with self.assertRaisesRegex(ValueError, "periodo"):
                download_snapshot(source, 0)
            network.assert_not_called()

    def test_offline_provenance_cannot_be_changed(self):
        for field, value in (("period", "2020-01"), ("description", "Terrazas. Enero 2020"),
                             ("resource_id", RESOURCES[1]), ("sha256", "0" * 64)):
            item = payload(0)
            item["source"][field] = value
            with self.assertRaisesRegex(ValueError, "Procedencia"):
                validate_payload(item, 0)

    def test_offline_extra_personal_field_rejected(self):
        item = payload(0)
        next(iter(item["records"].values()))["telefono"] = "12345"
        with self.assertRaisesRegex(ValueError, "Campos"):
            validate_payload(item, 0)

    def test_offline_sanitized_hash_detects_modified_value(self):
        item = payload(0)
        next(iter(item["records"].values()))["district"] = "DATOS ALTERADOS"
        with self.assertRaisesRegex(ValueError, "Hash"):
            validate_payload(item, 0)

    def test_redirect_rejected_before_following_destination(self):
        request = urllib.request.Request(URLS[0])
        with patch.object(urllib.request.HTTPRedirectHandler, "redirect_request") as follow:
            with self.assertRaises(ValueError):
                OfficialRedirectHandler().redirect_request(request, None, 302, "Found", {}, "https://example.com/private")
            follow.assert_not_called()

    def test_second_download_failure_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for index, period in enumerate(PERIODS):
                (base / f"madrid-terrazas-{period}.json").write_text(json.dumps(payload(index)), encoding="utf-8")
            output = base / "radar.json"
            output.write_text("existing radar", encoding="utf-8")
            before = {p.name: p.read_bytes() for p in base.iterdir()}
            with patch("scripts.madrid.fetch", return_value=json.dumps({"result": catalog()}).encode()), \
                    patch("scripts.madrid.download_snapshot", side_effect=[payload(0), OSError("second download failed")]):
                with self.assertRaises(OSError):
                    build(output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in base.iterdir()})

    def test_second_download_failure_creates_no_partial_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.madrid.fetch", return_value=json.dumps({"result": catalog()}).encode()), \
                    patch("scripts.madrid.download_snapshot", side_effect=[payload(0), OSError("second download failed")]):
                with self.assertRaises(OSError):
                    build(Path(directory) / "radar.json")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_altered_baseline_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            item = payload(0)
            item["source"]["period"] = "2020-01"
            snapshot = base / f"madrid-terrazas-{PERIODS[0]}.json"
            snapshot.write_text(json.dumps(item), encoding="utf-8")
            before = snapshot.read_bytes()
            with patch("scripts.madrid.fetch", return_value=json.dumps({"result": catalog()}).encode()):
                with self.assertRaisesRegex(ValueError, "Procedencia"):
                    build(base / "radar.json")
            self.assertEqual(before, snapshot.read_bytes())
            self.assertFalse((base / "radar.json").exists())

    def test_verified_offline_snapshots_accepted(self):
        validate_payload(payload(0), 0)
        validate_payload(payload(1), 1)


if __name__ == "__main__":
    unittest.main()
