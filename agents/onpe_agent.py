from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Any

from config import (
    CACHE_PATH,
    CANDIDATE_A_NAME,
    CANDIDATE_B_NAME,
    MOCK_SEED,
    RATE_LIMIT_SECONDS,
    SNAPSHOTS_PATH,
    SOURCE_MODE,
)
from storage.json_store import ensure_parent, read_json, read_jsonl, write_json

CACHE_VERSION = 4
START_PROGRESS_PCT = 60.0
PROGRESS_STEP_PCT = 3.1


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
