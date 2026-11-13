"""Shared fail-closed schema for publishable radar artifacts (standard library).

This validates structure and internal provenance consistency, not the truth of
arbitrary external records. The Madrid importer additionally pins source hashes.
"""
from collections import Counter
from datetime import date, datetime, timezone
import re
from urllib.parse import urlsplit

MUNICIPAL = "https://datos.madrid.es/dataset/209548-0-censo-locales-historico"
POPULATION = "https://datos.madrid.es/dataset/300557-0-poblacion-distrito-barrio"
DISTRICT_CONTEXT = {"terraces_date", "population_date", "population_source", "rows"}
BARRIO_ROW = {"key", "name", "terraces", "population"}
POPULATION_SOURCE = {"url", "dataset", "resource_id", "description", "date", "sha256", "bytes", "neighborhoods"}
TYPES = {"entrada", "salida", "cambio_estado", "cambio_actividad"}
META_REQUIRED = {"source_url", "from_date", "to_date", "generated_at", "mode",
                 "total_changes", "displayed_changes", "counts", "sources", "coverage_note"}
META_OPTIONAL = {"license", "license_url", "attribution", "date_note", "selection_note", "privacy_note"}
CHANGE_FIELDS = {"id", "local_id", "district", "neighborhood", "activity", "type", "before", "after", "changed_fields"}
SOURCE_FIELDS = {"url", "resource_id", "period", "description", "sha256", "bytes", "quality"}
QUALITY_FIELDS = {"rows", "unique_ids", "identical_duplicates", "source_load_dates"}
CHANGED_FIELDS = {"local_id", "district", "neighborhood", "activity", "local_status", "terrace_status", "period"}


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        raise ValueError("Radar: campos ausentes o no autorizados")


def _text(value, limit=2000):
    if (not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit
            or any(ord(char) < 32 for char in value) or re.search(r"[<>]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)):
        raise ValueError("Radar: texto inválido, marcado o contacto personal no permitido")
    return value


def _integer(value, minimum=0, maximum=10000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Radar: contador entero fuera de rango")
    return value


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Radar: fecha ISO inválida")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Radar: fecha ISO inexistente") from None
    if parsed > datetime.now(timezone.utc).date():
        raise ValueError("Radar: fecha futura")
    return parsed


def _url(value, hosts):
    _text(value)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username
                 and not parsed.password and parsed.port in (None, 443) and not parsed.fragment
                 and not any(char.isspace() for char in value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Radar: URL fuera del origen HTTPS autorizado")
    return value


def validate_radar(payload):
    """Return the same payload or raise ValueError before publication/registration."""
    _object(payload, {"meta", "changes"}, {"districts", "series"})
    meta, changes = payload["meta"], payload["changes"]
    _object(meta, META_REQUIRED, META_OPTIONAL)
    mode = meta["mode"]
    if mode not in ("real", "synthetic"):
        raise ValueError("Radar: modo real o synthetic obligatorio")
    start, end = _date(meta["from_date"]), _date(meta["to_date"])
    if start >= end:
        raise ValueError("Radar: cortes fuera de orden")
    _text(meta["generated_at"], 40)
    try:
        generated = datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Radar: instante de generación inválido") from None
    if (generated.tzinfo is None or generated > datetime.now(timezone.utc)
            or generated.date() < end):
        raise ValueError("Radar: generación sin zona, futura o anterior a los datos")
    allowed_hosts = {"datos.madrid.es"} if mode == "real" else {"datos.madrid.es", "example.com", "example.org"}
    _url(meta["source_url"], allowed_hosts)
    if mode == "real" and meta["source_url"] != MUNICIPAL:
        raise ValueError("Radar real: fuente municipal no reconocida")
    for key in META_OPTIONAL | {"coverage_note"}:
        if key in meta:
            _text(meta[key])
    if "license_url" in meta:
        _url(meta["license_url"], {"creativecommons.org"})
    if mode == "real" and (meta.get("license") != "CC BY 4.0" or not meta.get("attribution")):
        raise ValueError("Radar real: licencia y atribución obligatorias")
    if not isinstance(changes, list) or len(changes) > 300:
        raise ValueError("Radar: changes debe ser una lista de hasta 300 registros")
    total = _integer(meta["total_changes"])
    displayed = _integer(meta["displayed_changes"], maximum=300)
    if displayed != len(changes) or total < displayed:
        raise ValueError("Radar: total o registros mostrados incoherentes")
    counts = meta["counts"]
    if not isinstance(counts, dict) or counts.keys() - TYPES:
        raise ValueError("Radar: categorías de conteo inválidas")
    if sum(_integer(value) for value in counts.values()) != total:
        raise ValueError("Radar: sumario no coincide con el total")
    seen, actual = set(), Counter()
    for item in changes:
        _object(item, CHANGE_FIELDS)
        for key in ("id", "local_id", "district", "neighborhood", "activity", "type"):
            _text(item[key], 200)
        identifier_pattern = r"[0-9]{1,20}" if mode == "real" else r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}"
        if not re.fullmatch(identifier_pattern, item["id"]) or not re.fullmatch(identifier_pattern, item["local_id"]):
            raise ValueError("Radar: identificador inválido")
        if item["id"] in seen:
            raise ValueError("Radar: identificador duplicado")
        seen.add(item["id"])
        kind = item["type"]
        if kind not in TYPES:
            raise ValueError("Radar: tipo de cambio desconocido")
        for key in ("before", "after"):
            if item[key] is not None:
                _text(item[key], 1000)
        before, after = item["before"], item["after"]
        if (kind == "entrada" and (before is not None or after is None)
                or kind == "salida" and (before is None or after is not None)
                or kind.startswith("cambio_") and (before is None or after is None or before == after)):
            raise ValueError("Radar: estados anterior/posterior incompatibles con el cambio")
        fields = item["changed_fields"]
        if (not isinstance(fields, list) or not all(isinstance(field, str) and field in CHANGED_FIELDS for field in fields)
                or len(set(fields)) != len(fields)
                or kind in {"entrada", "salida"} and fields
                or kind.startswith("cambio_") and not fields):
            raise ValueError("Radar: campos modificados inválidos")
        actual[kind] += 1
    if any(actual[kind] > counts.get(kind, 0) for kind in actual):
        raise ValueError("Radar: registros superan sus conteos")
    if displayed == total and any(actual[kind] != counts.get(kind, 0) for kind in TYPES):
        raise ValueError("Radar: conteos no corresponden a los registros completos")
    sources = meta["sources"]
    if not isinstance(sources, list) or len(sources) not in ((2,) if mode == "real" else (0, 2)):
        raise ValueError("Radar: se requieren dos fuentes para los cortes reales")
    for index, source in enumerate(sources):
        _object(source, SOURCE_FIELDS)
        _url(source["url"], allowed_hosts)
        _text(source["resource_id"], 100)
        _text(source["description"], 200)
        expected = (start, end)[index]
        if source["period"] != expected.strftime("%Y-%m"):
            raise ValueError("Radar: periodo de fuente distinto del corte")
        if not isinstance(source["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("Radar: hash SHA-256 inválido")
        _integer(source["bytes"], 1, 200000000)
        if mode == "real" and (not re.fullmatch(r"209548-[0-9]+-censo-locales-historico", source["resource_id"])
                or not source["url"].startswith(MUNICIPAL + "/resource/" + source["resource_id"] + "/download/")):
            raise ValueError("Radar: recurso municipal incompatible")
        quality = source["quality"]
        _object(quality, QUALITY_FIELDS)
        rows = _integer(quality["rows"], 1)
        unique = _integer(quality["unique_ids"], 1)
        duplicates = _integer(quality["identical_duplicates"])
        if rows != unique + duplicates or quality["source_load_dates"] != [expected.strftime("%d/%m/%Y")]:
            raise ValueError("Radar: calidad o fecha de carga incoherente")
    if mode == "real":
        if sources[0]["resource_id"] == sources[1]["resource_id"] or sources[0]["url"] == sources[1]["url"]:
            raise ValueError("Radar: los dos cortes deben tener recursos distintos")
        if sources[1]["quality"]["unique_ids"] - sources[0]["quality"]["unique_ids"] != counts.get("entrada", 0) - counts.get("salida", 0):
            raise ValueError("Radar: balance de entradas/salidas incompatible con los cortes")
    if "districts" in payload:
        _districts(payload["districts"], meta, mode)
    if "series" in payload:
        _series(payload["series"], meta, mode)
    return payload


SERIES_MONTH = {"period", "resource_id", "url", "description", "sha256", "bytes", "rows", "load_dates", "total", "districts", "barrios", "capacity"}
CAPACITY = {"m2_es", "m2_ra", "sillas_es", "sillas_ra", "anuales"}


def _series(series, meta, mode):
    """Serie mensual opcional: recuentos agregados por mes y distrito, terminada en el corte final."""
    _object(series, {"source_url", "license", "months"})
    hosts = {"datos.madrid.es"} if mode == "real" else {"datos.madrid.es", "example.com", "example.org"}
    _url(series["source_url"], hosts)
    if mode == "real" and series["source_url"] != MUNICIPAL or series["license"] != "CC BY 4.0":
        raise ValueError("Radar: serie fuera de la fuente municipal o sin licencia")
    months = series["months"]
    if not isinstance(months, list) or not 2 <= len(months) <= 240:
        raise ValueError("Radar: la serie necesita entre 2 y 240 meses")
    periods = []
    for month in months:
        _object(month, SERIES_MONTH)
        if not isinstance(month["period"], str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month["period"]):
            raise ValueError("Radar: mes de la serie inválido")
        periods.append(month["period"])
        _url(month["url"], hosts)
        _text(month["resource_id"], 100)
        _text(month["description"], 200)
        if mode == "real" and not month["url"].startswith(MUNICIPAL + "/resource/" + month["resource_id"] + "/download/"):
            raise ValueError("Radar: recurso de la serie incompatible")
        if not isinstance(month["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", month["sha256"]):
            raise ValueError("Radar: hash de la serie inválido")
        _integer(month["bytes"], 1, 200000000)
        _integer(month["rows"], 1)
        if (not isinstance(month["load_dates"], list) or len(month["load_dates"]) > 31
                or any(_date(value).isoformat() != value for value in month["load_dates"])):
            raise ValueError("Radar: fechas de carga de la serie inválidas")
        districts = month["districts"]
        if not isinstance(districts, dict) or not 1 <= len(districts) <= 40:
            raise ValueError("Radar: distritos de la serie inválidos")
        for name, count in districts.items():
            _text(name, 200)
            _integer(count)
        if sum(districts.values()) != _integer(month["total"], 1) or month["total"] > month["rows"]:
            raise ValueError("Radar: total mensual incoherente")
        barrios = month["barrios"]
        if not isinstance(barrios, dict) or len(barrios) > 300 or list(barrios) != sorted(barrios):
            raise ValueError("Radar: barrios de la serie inválidos")
        per_district = Counter()
        for name, count in barrios.items():
            _text(name, 300)
            per_district[name.split("|")[0]] += _integer(count)
        if per_district and any(per_district.get(name, 0) != count for name, count in districts.items() if name != "SIN DISTRITO"):
            raise ValueError("Radar: los barrios de la serie no suman su distrito")
        capacity = month["capacity"]
        if capacity is not None:
            if not isinstance(capacity, dict) or set(capacity) != set(districts):
                raise ValueError("Radar: capacidad de la serie sin los mismos distritos")
            for name, values in capacity.items():
                _object(values, CAPACITY)
                for key in CAPACITY:
                    _integer(values[key], 0, 100000000)
                if values["anuales"] > districts[name]:
                    raise ValueError("Radar: más terrazas anuales que terrazas")
    if periods != sorted(set(periods)):
        raise ValueError("Radar: meses de la serie duplicados o desordenados")
    last, final = months[-1], meta["sources"][1] if len(meta["sources"]) == 2 else None
    if final is not None and (last["period"] != final["period"] or last["sha256"] != final["sha256"]
                              or last["total"] != final["quality"]["unique_ids"]):
        raise ValueError("Radar: la serie no termina en el corte final comparado")


def _districts(context, meta, mode):
    """Contexto opcional: terrazas del corte final y población del padrón por distrito."""
    _object(context, DISTRICT_CONTEXT, {"barrios"})
    if context["terraces_date"] != meta["to_date"]:
        raise ValueError("Radar: el recuento por distrito debe ser del corte final")
    _date(context["terraces_date"])
    source = context["population_source"]
    _object(source, POPULATION_SOURCE)
    if _date(context["population_date"]).isoformat() != source["date"]:
        raise ValueError("Radar: fecha del padrón incoherente")
    hosts = {"datos.madrid.es"} if mode == "real" else {"datos.madrid.es", "example.com", "example.org"}
    _url(source["url"], hosts)
    _url(source["dataset"], hosts)
    _text(source["resource_id"], 100)
    _text(source["description"], 200)
    if not isinstance(source["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
        raise ValueError("Radar: hash SHA-256 del padrón inválido")
    _integer(source["bytes"], 1, 200000000)
    _integer(source["neighborhoods"], 1, 1000)
    if mode == "real" and (source["dataset"] != POPULATION
                           or not source["url"].startswith(POPULATION + "/resource/" + source["resource_id"] + "/download/")):
        raise ValueError("Radar: padrón fuera del conjunto municipal fijado")
    rows = context["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError("Radar: entre 1 y 40 distritos")
    names = []
    for row in rows:
        _object(row, {"district", "terraces", "population"})
        names.append(_text(row["district"], 200))
        _integer(row["terraces"])
        _integer(row["population"], 1)
    if len(set(names)) != len(names) or names != sorted(names):
        raise ValueError("Radar: distritos duplicados o desordenados")
    if mode == "real" and sum(row["terraces"] for row in rows) != meta["sources"][1]["quality"]["unique_ids"]:
        raise ValueError("Radar: el recuento por distrito no suma el corte final")
    if "barrios" in context:
        barrios = context["barrios"]
        if not isinstance(barrios, list) or not 1 <= len(barrios) <= 300:
            raise ValueError("Radar: barrios inválidos")
        keys, by_district = [], Counter()
        for row in barrios:
            _object(row, BARRIO_ROW)
            keys.append(_text(row["key"], 300))
            _text(row["name"], 200)
            by_district[row["key"].split("|")[0]] += _integer(row["terraces"])
            _integer(row["population"], 1)
        if keys != sorted(set(keys)):
            raise ValueError("Radar: barrios duplicados o desordenados")
        if dict(by_district) != {row["district"]: row["terraces"] for row in rows}:
            raise ValueError("Radar: los barrios no suman su distrito")
