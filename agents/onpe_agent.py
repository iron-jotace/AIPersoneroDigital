from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from config import (
    CACHE_PATH,
    CANDIDATE_A_NAME,
    CANDIDATE_B_NAME,
    MOCK_SEED,
    ONPE_BASE_URL,
    ONPE_CACHE_TTL_SECONDS,
    ONPE_ID_ELECCION,
    ONPE_PARTICIPANTS_ENDPOINT,
    ONPE_PORTAL_URL,
    ONPE_PROCESS_ENDPOINT,
    ONPE_TIPO_FILTRO,
    ONPE_TOTALS_ENDPOINT,
    RATE_LIMIT_SECONDS,
    REAL_ONPE_ENABLED,
    SNAPSHOTS_PATH,
    SOURCE_MODE,
    USER_AGENT,
)
from storage.json_store import canonical_hash, ensure_parent, read_json, read_jsonl, write_json

CACHE_VERSION = 4
START_PROGRESS_PCT = 60.0
PROGRESS_STEP_PCT = 3.1
_REAL_SNAPSHOT_CACHE: dict[str, Any] = {"fetched_at_epoch": 0.0, "snapshot": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_sequence_from_bronze() -> int:
    snapshots = read_jsonl(SNAPSHOTS_PATH)
    if not snapshots:
        return 1
    return max(int(item["snapshot"].get("sequence", 0)) for item in snapshots) + 1


def _progress_for_sequence(sequence: int) -> float:
    return min(100.0, START_PROGRESS_PCT + (sequence - 1) * PROGRESS_STEP_PCT)


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100, 2)


def _base_rows(rng: random.Random, progress: float, sequence: int) -> list[dict[str, Any]]:
    mesas = [
        ("LIMA", "LIMA", "150101", "000001"),
        ("LIMA", "ATE", "150103", "000002"),
        ("PIURA", "PIURA", "200101", "000003"),
        ("CUSCO", "CUSCO", "080101", "000004"),
        ("AREQUIPA", "AREQUIPA", "040101", "000005"),
        ("LORETO", "MAYNAS", "160101", "000006"),
    ]
    rows: list[dict[str, Any]] = []
    for idx, (region, province, ubigeo, mesa) in enumerate(mesas):
        counted_factor = progress / 100
        electores = 245 + idx * 17
        actas_total = 120 + idx * 11
        actas_counted = actas_total if progress >= 99.5 else min(actas_total, int(actas_total * counted_factor))
        counted_share = actas_counted / actas_total
        base_a = int((1250 + idx * 140) * counted_share)
        base_b = int((1190 + idx * 135) * counted_share)
        noise = rng.randint(-10, 10)
        if idx == 3 and sequence % 12 == 7:
            noise += 220
        rows.append(
            {
                "region": region,
                "province": province,
                "ubigeo": ubigeo,
                "mesa_sample": mesa,
                "electores_habiles": electores * actas_total,
                "actas_total": actas_total,
                "actas_contabilizadas": actas_counted,
                "actas_observadas": rng.randint(0, 4),
                "candidate_a_name": CANDIDATE_A_NAME,
                "candidate_b_name": CANDIDATE_B_NAME,
                "candidate_a_votes": max(0, base_a + noise),
                "candidate_b_votes": max(0, base_b - noise),
                "votos_blancos": 20 + idx * 3 + rng.randint(0, 5),
                "votos_nulos": 26 + idx * 4 + rng.randint(0, 7),
            }
        )
    return rows


def fetch_onpe_snapshot(force: bool = False) -> dict[str, Any]:
    """Return deterministic fake electoral data with local cache and rate limiting."""
    ensure_parent(CACHE_PATH)
    cached = read_json(CACHE_PATH)
    cache_valid = bool(cached and cached.get("cache_version") == CACHE_VERSION)
    now = time.time()
    sequence = _next_sequence_from_bronze()
    cached_sequence = cached.get("snapshot", {}).get("sequence") if cache_valid else None
    if (
        cache_valid
        and not force
        and cached_sequence == sequence
        and now - cached.get("fetched_at_epoch", 0) < RATE_LIMIT_SECONDS
    ):
        return cached["snapshot"]

    progress = _progress_for_sequence(sequence)
    rng = random.Random(MOCK_SEED + sequence)
    rows = _base_rows(rng, progress, sequence)
    total_actas = sum(row["actas_total"] for row in rows)
    counted_actas = sum(row["actas_contabilizadas"] for row in rows)
    candidate_a_votes = sum(row["candidate_a_votes"] for row in rows)
    candidate_b_votes = sum(row["candidate_b_votes"] for row in rows)
    candidate_votes = candidate_a_votes + candidate_b_votes
    vote_gap_abs = abs(candidate_a_votes - candidate_b_votes)

    snapshot = {
        "source": "MOCK_ONPE_PUBLIC_DATA",
        "source_mode": SOURCE_MODE,
        "collection_mode": "mock_passive_public_snapshot",
        "sequence": sequence,
        "captured_at": _now_iso(),
        "election_id": "PER-GENERAL-MOCK-2026",
        "candidate_a_name": CANDIDATE_A_NAME,
        "candidate_b_name": CANDIDATE_B_NAME,
        "candidate_a_votes": candidate_a_votes,
        "candidate_b_votes": candidate_b_votes,
        "candidate_a_pct": _pct(candidate_a_votes, candidate_votes),
        "candidate_b_pct": _pct(candidate_b_votes, candidate_votes),
        "vote_gap_abs": vote_gap_abs,
        "vote_gap_pct": _pct(vote_gap_abs, candidate_votes),
        "actas_contabilizadas_pct": round((counted_actas / total_actas) * 100, 2),
        "national_totals": {
            "actas_total": total_actas,
            "actas_contabilizadas": counted_actas,
            "candidate_a_votes": candidate_a_votes,
            "candidate_b_votes": candidate_b_votes,
            "votos_blancos": sum(row["votos_blancos"] for row in rows),
            "votos_nulos": sum(row["votos_nulos"] for row in rows),
        },
        "rows": rows,
    }
    write_json(
        CACHE_PATH,
        {"cache_version": CACHE_VERSION, "fetched_at_epoch": now, "sequence": sequence, "snapshot": snapshot},
    )
    return json.loads(json.dumps(snapshot, sort_keys=True))


def fetch_real_onpe_snapshot(force: bool = False) -> dict[str, Any]:
    """Fetch a national second-round snapshot from validated public ONPE endpoints.

    Safe operating constraints:
    - Passive read-only public-data access only.
    - No authentication bypass.
    - No aggressive scraping.
    - Rate limiting must be respected.
    """
    if not REAL_ONPE_ENABLED:
        raise RuntimeError("REAL_READ_ONLY connector is disabled.")
    if SOURCE_MODE != "REAL_READ_ONLY":
        raise RuntimeError("REAL_READ_ONLY connector requires SOURCE_MODE='REAL_READ_ONLY'.")
    if not ONPE_BASE_URL or not ONPE_PROCESS_ENDPOINT or not ONPE_TOTALS_ENDPOINT or not ONPE_PARTICIPANTS_ENDPOINT:
        raise RuntimeError("REAL_READ_ONLY connector requires validated ONPE endpoint configuration.")

    now = time.time()
    cached = _REAL_SNAPSHOT_CACHE.get("snapshot")
    if cached and not force and now - float(_REAL_SNAPSHOT_CACHE["fetched_at_epoch"]) < ONPE_CACHE_TTL_SECONDS:
        return json.loads(json.dumps(cached, sort_keys=True))

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Referer": ONPE_PORTAL_URL,
    }
    params = {"idEleccion": ONPE_ID_ELECCION, "tipoFiltro": ONPE_TIPO_FILTRO}
    with requests.Session() as session:
        session.headers.update(headers)
        process_response = _get_json(session, ONPE_PROCESS_ENDPOINT)
        totals_response = _get_json(session, ONPE_TOTALS_ENDPOINT, params=params)
        participants_response = _get_json(session, ONPE_PARTICIPANTS_ENDPOINT, params=params)

    process_data = _validate_process_response(process_response)
    totals_data = _validate_totals_response(totals_response)
    participants_data = _validate_participants_response(participants_response)
    keiko = _find_participant(participants_data, "KEIKO SOFIA FUJIMORI HIGUCHI")
    roberto = _find_participant(participants_data, "ROBERTO HELBERT SANCHEZ PALOMINO")

    candidate_a_votes = _to_int(_field(keiko, "totalVotosValidos"))
    candidate_b_votes = _to_int(_field(roberto, "totalVotosValidos"))
    candidate_a_pct = _to_float(_field(keiko, "porcentajeVotosValidos"))
    candidate_b_pct = _to_float(_field(roberto, "porcentajeVotosValidos"))
    raw_payload = {
        "process_response": process_response,
        "totals_response": totals_response,
        "participants_response": participants_response,
    }
    captured_at = _now_iso()
    snapshot = {
        "source": "ONPE_REAL_PUBLIC_DATA",
        "source_url": ONPE_PORTAL_URL,
        "source_mode": "REAL_READ_ONLY",
        "collection_mode": "real_read_only_public_snapshot",
        "artifact_type": "aggregate_snapshot",
        "sequence": _next_sequence_from_bronze(),
        "captured_at": captured_at,
        "captured_at_utc": captured_at,
        "election_id": process_data["acronimo"],
        "candidate_a_name": CANDIDATE_A_NAME,
        "candidate_b_name": CANDIDATE_B_NAME,
        "candidate_a_votes": candidate_a_votes,
        "candidate_b_votes": candidate_b_votes,
        "candidate_a_pct": candidate_a_pct,
        "candidate_b_pct": candidate_b_pct,
        "vote_gap_abs": candidate_a_votes - candidate_b_votes,
        "vote_gap_pct": round(candidate_a_pct - candidate_b_pct, 3),
        "actas_contabilizadas_pct": _to_float(totals_data["actasContabilizadas"]),
        "actas_contabilizadas": _to_int(totals_data["contabilizadas"]),
        "total_actas": _to_int(totals_data["totalActas"]),
        "total_votos_validos": _to_int(totals_data["totalVotosValidos"]),
        "total_votos_emitidos": _to_int(totals_data.get("totalVotosEmitidos", 0)),
        "fecha_actualizacion_onpe": totals_data.get("fechaActualizacion"),
        "snapshot_hash": canonical_hash(raw_payload),
    }
    _REAL_SNAPSHOT_CACHE["fetched_at_epoch"] = now
    _REAL_SNAPSHOT_CACHE["snapshot"] = snapshot
    return json.loads(json.dumps(snapshot, sort_keys=True))


def select_onpe_snapshot_source(force: bool = False) -> dict[str, Any]:
    if SOURCE_MODE == "MOCK":
        return fetch_onpe_snapshot(force=force)
    if SOURCE_MODE == "REAL_READ_ONLY":
        return fetch_real_onpe_snapshot(force=force)
    raise ValueError(f"Unsupported SOURCE_MODE: {SOURCE_MODE}")


def _get_json(
    session: requests.Session,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.get(urljoin(ONPE_BASE_URL, endpoint), params=params, timeout=15)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type.lower():
        raise RuntimeError(f"ONPE endpoint returned non-JSON content: {content_type}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("ONPE endpoint returned an unexpected JSON shape.")
    return payload


def _validate_success(payload: dict[str, Any], label: str) -> dict[str, Any]:
    if payload.get("success") is not True:
        raise RuntimeError(f"ONPE {label} response was not successful.")
    data = payload.get("data")
    if data is None:
        raise RuntimeError(f"ONPE {label} response did not include data.")
    return data


def _validate_process_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate_success(payload, "process")
    if not isinstance(data, dict):
        raise RuntimeError("ONPE process data had an unexpected shape.")
    if "SEGUNDA ELECCION PRESIDENCIAL 2026" not in str(data.get("nombre", "")):
        raise RuntimeError("ONPE process data is not the validated second-round process.")
    if data.get("acronimo") != "SEP2026":
        raise RuntimeError("ONPE process acronym did not match SEP2026.")
    if _to_int(data.get("idEleccionPrincipal")) != ONPE_ID_ELECCION:
        raise RuntimeError("ONPE process election id did not match configuration.")
    return data


def _validate_totals_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate_success(payload, "totals")
    if not isinstance(data, dict):
        raise RuntimeError("ONPE totals data had an unexpected shape.")
    for key in ["actasContabilizadas", "contabilizadas", "totalActas", "totalVotosValidos"]:
        if key not in data:
            raise RuntimeError(f"ONPE totals data missing required field: {key}")
    return data


def _validate_participants_response(payload: dict[str, Any]) -> Any:
    data = _validate_success(payload, "participants")
    serialized = json.dumps(data, ensure_ascii=False).upper()
    for name in ["KEIKO SOFIA FUJIMORI HIGUCHI", "ROBERTO HELBERT SANCHEZ PALOMINO"]:
        if name not in serialized:
            raise RuntimeError(f"ONPE participants data missing required candidate: {name}")
    return data


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nested = [value]
        for item in value.values():
            nested.extend(_walk_dicts(item))
        return nested
    if isinstance(value, list):
        nested: list[dict[str, Any]] = []
        for item in value:
            nested.extend(_walk_dicts(item))
        return nested
    return []


def _find_participant(data: Any, candidate_name: str) -> dict[str, Any]:
    for item in _walk_dicts(data):
        if candidate_name in json.dumps(item, ensure_ascii=False).upper():
            return item
    raise RuntimeError(f"Could not locate participant data for {candidate_name}.")


def _field(item: dict[str, Any], field_name: str) -> Any:
    if field_name in item:
        return item[field_name]
    lowered = field_name.lower()
    for key, value in item.items():
        if key.lower() == lowered:
            return value
    raise RuntimeError(f"Participant data missing required field: {field_name}")


def _to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    normalized = str(value).replace(",", "").replace(" ", "")
    return int(float(normalized))


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).replace("%", "").replace(" ", "")
    if "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")
    else:
        normalized = normalized.replace(",", "")
    return float(normalized)
