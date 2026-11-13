"""Reproducible Madrid terrace register comparison; Python standard library only.

Raw responses remain in memory. Only an explicit non-personal field allowlist is
persisted. Differences describe the register, never real openings or closures.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import urllib.parse
import urllib.request

DATASET = "https://datos.madrid.es/dataset/209548-0-censo-locales-historico"
API = "https://datos.madrid.es/api/3/action/package_show?id=209548-0-censo-locales-historico"
RESOURCES = ("209548-860-censo-locales-historico", "209548-872-censo-locales-historico")
PERIODS = ("2026-09", "2026-10")
DATES = ("2026-09-30", "2026-10-31")
MAX_BYTES = 20_000_000
REQUIRED = {"id_terraza", "id_local", "desc_distrito_local", "desc_barrio_local",
            "desc_situacion_local", "desc_situacion_terraza", "desc_periodo_terraza"}
ACTIVITY = "Hostelería con terraza (registro municipal)"
DESCRIPTIONS = ("Terrazas. Septiembre 2026", "Terrazas. Octubre 2026")
LOAD_DATES = ("30/09/2026", "31/10/2026")
RAW_HASHES = ("a46b1017e7bd3af30f785283e51ce267c4ed55f8b83124e7e5b9656e8b35066c",
              "739da3d27886af0c91e064741ca6bb63628aa2a51631b01357705a33bcd26409")
RECORD_HASHES = ("d820a7c215c3888920c8b12696b35b0baa5ae004ec5b937c60505ee12f53f1f7",
                 "d79be62aeb1d0aeac106054af99339bddaa9b5dfaf454d53abf04be2429021b4")
SIZES = (5193282, 5207449)
ROWS = (6594, 6612)
URLS = (DATASET + "/resource/" + RESOURCES[0] + "/download/209548_20261001_044627.csv",
        DATASET + "/resource/" + RESOURCES[1] + "/download/209548-0-censo-locales-historico_19_20261101_061610.csv")
RECORD_FIELDS = {"id", "local_id", "district", "neighborhood", "activity",
                 "local_status", "terrace_status", "period"}


def validate_url(url):
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "datos.madrid.es"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Solo se permiten recursos HTTPS oficiales de datos.madrid.es")


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)  # Reject BEFORE urllib opens the redirected destination.
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "WebFactory-Validation/1.0"})
    opener = urllib.request.build_opener(OfficialRedirectHandler())
    with opener.open(request, timeout=45) as response:
        validate_url(response.url)
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Respuesta superior al límite de 20 MB")
    return raw


def parse_snapshot(raw, expected_date=None):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=";")
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError("Esquema municipal incompatible: faltan " + ", ".join(sorted(REQUIRED - set(reader.fieldnames or []))))
    records, duplicates, load_dates = {}, 0, set()
    for line, row in enumerate(reader, 2):
        # Ignore blank lines; reject malformed or missing identifiers.
        if None in row or any(row.get(key) is None for key in REQUIRED):
            raise ValueError(f"Fila CSV incompleta o con campos extra: {line}")
        if expected_date and row.get("fx_carga", "").strip() != expected_date:
            raise ValueError(f"Fecha fx_carga distinta del corte esperado: fila {line}")
        key, local = row["id_terraza"].strip(), row["id_local"].strip()
        if not key.isdecimal() or not local.isdecimal():
            raise ValueError(f"Identificador municipal inválido: fila {line}")
        item = {
            "id": key, "local_id": local,
            "district": row["desc_distrito_local"].strip(),
            "neighborhood": row["desc_barrio_local"].strip(),
            "activity": ACTIVITY,
            "local_status": row["desc_situacion_local"].strip(),
            "terrace_status": row["desc_situacion_terraza"].strip(),
            "period": row["desc_periodo_terraza"].strip(),
        }
        if not all(item.values()):
            raise ValueError(f"Campo obligatorio vacío: fila {line}")
        if key in records:
            if records[key] != item:
                raise ValueError(f"Clave de terraza duplicada con valores incompatibles: {key}")
            duplicates += 1
        records[key] = item
        if row.get("fx_carga", "").strip():
            load_dates.add(row["fx_carga"].strip())
    if not records:
        raise ValueError("Corte vacío: no se puede interpretar como desaparición de todos los registros")
    return records, {"rows": len(records) + duplicates, "unique_ids": len(records),
                     "identical_duplicates": duplicates, "source_load_dates": sorted(load_dates)}


def validate_payload(payload, index):
    if not isinstance(payload, dict) or set(payload) != {"source", "records"}:
        raise ValueError("Esquema de corte saneado incompatible")
    source, records = payload["source"], payload["records"]
    expected = {"url": URLS[index], "resource_id": RESOURCES[index], "period": PERIODS[index],
                "description": DESCRIPTIONS[index], "sha256": RAW_HASHES[index], "bytes": SIZES[index],
                "quality": {"rows": ROWS[index], "unique_ids": ROWS[index], "identical_duplicates": 0,
                            "source_load_dates": [LOAD_DATES[index]]}}
    if source != expected:
        raise ValueError("Procedencia, periodo o hash del corte distintos de la referencia verificada")
    if not isinstance(records, dict) or len(records) != ROWS[index]:
        raise ValueError("Número de registros distinto de la referencia verificada")
    for key, record in records.items():
        if (not isinstance(record, dict) or set(record) != RECORD_FIELDS
                or not all(isinstance(value, str) and value.strip() == value and value for value in record.values())
                or not key.isascii() or not key.isdecimal() or record["id"] != key
                or not record["local_id"].isascii() or not record["local_id"].isdecimal()
                or record["activity"] != ACTIVITY):
            raise ValueError("Campos no autorizados o identificadores inválidos en corte saneado")
    digest = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    if digest != RECORD_HASHES[index]:
        raise ValueError("Hash del corte saneado alterado; conservar referencia y revisar")


def download_snapshot(catalog, index):
    resource = next(item for item in catalog["resources"] if item["id"] == RESOURCES[index])
    if (resource["format"].upper() != "CSV" or resource["description"] != DESCRIPTIONS[index]
            or resource["url"] != URLS[index]):
        raise ValueError("Recurso o periodo municipal distinto al esperado")
    raw = fetch(resource["url"])
    if len(raw) != SIZES[index] or int(resource.get("size", 0)) != SIZES[index]:
        raise ValueError("Tamaño descargado distinto de la referencia: revisión necesaria")
    records, quality = parse_snapshot(raw, expected_date=LOAD_DATES[index])
    source = {"url": resource["url"], "resource_id": RESOURCES[index], "period": PERIODS[index],
              "description": resource["description"], "sha256": hashlib.sha256(raw).hexdigest(),
              "bytes": len(raw), "quality": quality}
    payload = {"source": source, "records": records}
    validate_payload(payload, index)
    return payload


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def describe(record):
    if record is None:
        return None
    return (f"Local: {record['local_status']}; terraza: {record['terrace_status']}; "
            f"periodo: {record['period']}; {record['district']} / {record['neighborhood']}; "
            f"local municipal {record['local_id']}")


def compare(before, after):
    changes = []
    for key in sorted(before.keys() | after.keys(), key=int):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        kind = "entrada" if old is None else "salida" if new is None else "cambio_estado"
        record = new or old
        changes.append({"id": key, "local_id": record["local_id"],
                        "district": record["district"], "neighborhood": record["neighborhood"],
                        "activity": ACTIVITY, "type": kind,
                        "before": describe(old), "after": describe(new),
                        "changed_fields": [field for field in record if old and new and old[field] != new[field]]})
    return changes


def monthly_series(series_path, final_source):
    """Serie mensual hasta el corte final; su último mes debe ser exactamente ese corte."""
    if not series_path.exists():
        return None
    import sys
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from madrid_serie import load  # import diferido: madrid_serie importa este módulo
    data = load(series_path)
    months = [month for month in data["months"] if month["period"] <= final_source["period"]]
    if not months or months[-1]["period"] != final_source["period"] or months[-1]["sha256"] != final_source["sha256"]:
        raise ValueError("La serie mensual no termina en el corte final comparado; revisión humana necesaria")
    return {**data, "months": months}


def district_context(population_path, final_records):
    """Terrazas del corte final y población del padrón por distrito, si existe el padrón saneado."""
    if not population_path.exists():
        return None
    import sys
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from madrid_poblacion import barrio_key, load  # import diferido: madrid_poblacion importa este módulo
    population = load(population_path)
    terraces = Counter(item["district"] for item in final_records.values())
    if set(terraces) != set(population["districts"]):
        raise ValueError("Distritos del registro y del padrón no coinciden; revisión humana necesaria")
    return {"terraces_date": DATES[1], "population_date": population["source"]["date"],
            "population_source": population["source"],
            "rows": [{"district": name, "terraces": terraces[name], "population": people}
                     for name, people in sorted(population["districts"].items())],
            "barrios": barrio_rows(final_records, population["barrios"], barrio_key)}


def barrio_rows(final_records, barrios, barrio_key):
    counts = Counter(barrio_key(item["district"], item["neighborhood"]) for item in final_records.values())
    unknown = set(counts) - set(barrios)
    if unknown:
        raise ValueError("Barrios del registro sin equivalencia en el padrón: " + ", ".join(sorted(unknown)))
    return [{"key": key, "name": value["name"], "terraces": counts[key], "population": value["population"]}
            for key, value in sorted(barrios.items())]


def build(output: Path, download=True, limit=300):
    if not 1 <= limit <= 300:
        raise ValueError("Límite de presentación entre 1 y 300")
    sources, snapshots, pending = [], [], []
    catalog = json.loads(fetch(API))["result"] if download else None
    if catalog and catalog.get("license_id") != "cc-by":
        raise ValueError("Licencia cambiada: revisión humana necesaria")
    for index, period in enumerate(PERIODS):
        snapshot_path = output.parent / f"madrid-terrazas-{period}.json"
        baseline = None
        if snapshot_path.exists():
            baseline = json.loads(snapshot_path.read_text(encoding="utf-8"))
            validate_payload(baseline, index)
        if download:
            payload = download_snapshot(catalog, index)
            validate_payload(payload, index)
            if baseline is not None and payload != baseline:
                raise ValueError("El nuevo corte difiere del baseline; no se sobrescribe")
            if baseline is None:
                pending.append((snapshot_path, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
        else:
            if baseline is None:
                raise ValueError("Falta corte saneado para reproducción offline")
            payload = baseline
        snapshots.append(payload["records"])
        sources.append(payload["source"])
    changes = compare(*snapshots)
    counts = dict(Counter(item["type"] for item in changes))
    result = {"meta": {
        "source_url": DATASET, "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Ayuntamiento de Madrid, Censo de locales y actividades, histórico de terrazas. Transformado por Web Factory IA.",
        "from_date": DATES[0], "to_date": DATES[1],
        "date_note": f"Fechas verificadas en fx_carga de los CSV ({LOAD_DATES[0]} y {LOAD_DATES[1]}); no son fechas de cambios individuales.",
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "real",
        "total_changes": len(changes), "displayed_changes": min(limit, len(changes)),
        "counts": counts, "sources": sources,
        "coverage_note": "Solo registros de terrazas de hostelería de Madrid. No cubre todos los locales. Entradas y salidas del registro no prueban aperturas o cierres reales. Cambios de estado incluyen periodo, local vinculado y barrio. No se comparan mesas, superficies ni permisos.",
        "selection_note": "Primeros identificadores numéricos de terraza; sin priorización comercial ni muestreo estadístico.",
        "privacy_note": "Sin rótulos, nombres, contactos, direcciones exactas ni coordenadas. Solo identificadores administrativos y zonas.",
    }, "changes": changes[:limit]}
    series = monthly_series(output.parent / "madrid-terrazas-serie.json", sources[1])
    if series is not None:
        result["series"] = series
    context = district_context(output.parent / "madrid-poblacion-2026.json", snapshots[1])
    if context is not None:
        result["districts"] = context
    # No writes occur until BOTH downloads and every baseline have passed validation.
    for path, text in pending:
        atomic_write(path, text)
    atomic_write(output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/radar.json"))
    parser.add_argument("--offline", action="store_true", help="Regenerar desde cortes saneados sin red")
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()
    result = build(args.output, download=not args.offline, limit=args.limit)
    print(json.dumps({key: result["meta"][key] for key in ("mode", "total_changes", "displayed_changes", "counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
