from __future__ import annotations

from typing import Any

from models.ers import compute_ers
from models.mad import mad_z_scores

MIN_MOVEMENTS_FOR_MAD = 3
MAD_ANOMALY_THRESHOLD = 3.5
MIN_GAP_DELTA_FOR_ANOMALY = 10_000
MIN_ACTAS_PCT_DELTA_FOR_ANOMALY = 0.10


def _vote_gap(snapshot: dict[str, Any]) -> int:
    if "candidate_a_votes" in snapshot and "candidate_b_votes" in snapshot:
        return int(snapshot["candidate_a_votes"] - snapshot["candidate_b_votes"])
    totals = snapshot.get("national_totals", {})
    return int(totals.get("candidate_a_votes", 0) - totals.get("candidate_b_votes", 0))


def _actas_pct(snapshot: dict[str, Any]) -> float:
    return float(snapshot.get("actas_contabilizadas_pct", 0.0))


def _direction_label(previous_gap: int, gap_delta: int) -> str:
    if gap_delta == 0:
        return "GAP_UNCHANGED"
    if previous_gap < 0:
        return "GAP_COMPRESSED_AGAINST_LEADER" if gap_delta > 0 else "GAP_EXPANDED_FOR_LEADER"
    return "GAP_COMPRESSED_AGAINST_LEADER" if gap_delta < 0 else "GAP_EXPANDED_FOR_LEADER"


def _movement_records(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for previous, current in zip(history, history[1:]):
        previous_snapshot = previous["snapshot"]
        current_snapshot = current["snapshot"]
        previous_gap = _vote_gap(previous_snapshot)
        current_gap = _vote_gap(current_snapshot)
        gap_delta = current_gap - previous_gap
        actas_pct_delta = _actas_pct(current_snapshot) - _actas_pct(previous_snapshot)

        # Exact duplicate captures do not carry movement information and should
        # not make the robust MAD baseline artificially quiet.
        if gap_delta == 0 and actas_pct_delta == 0:
            continue

        # The detector scores normalized movement per percentage point of actas
        # counted. Non-progressing actas deltas are skipped to avoid undefined
        # or misleading per-actas rates.
        if actas_pct_delta <= 0:
            continue

        gap_delta_per_actas_pct = gap_delta / actas_pct_delta
        records.append(
            {
                "history_item": current,
                "gap_delta": gap_delta,
                "actas_pct_delta": actas_pct_delta,
                "gap_delta_per_actas_pct": gap_delta_per_actas_pct,
                "direction": _direction_label(previous_gap, gap_delta),
            }
        )
    return records


def _passes_materiality(record: dict[str, Any]) -> bool:
    return (
        abs(record["gap_delta"]) >= MIN_GAP_DELTA_FOR_ANOMALY
        and record["actas_pct_delta"] >= MIN_ACTAS_PCT_DELTA_FOR_ANOMALY
    )


def detect_gap_anomalies(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect unusual vote-gap movement after an explicit warm-up period.

    MAD scores are absolute, so unusually large negative and positive movements
    are treated symmetrically by magnitude. At least three non-duplicate,
    forward-progress movement records are required before scoring. A high
    normalized movement only opens a case when the latest movement is also
    materially large in absolute vote delta and actas percentage progress.
    """
    if len(history) < 4:
        return []

    records = _movement_records(history)
    if len(records) < MIN_MOVEMENTS_FOR_MAD:
        return []
    if records[-1]["history_item"] is not history[-1]:
        return []

    normalized_movements = [record["gap_delta_per_actas_pct"] for record in records]
    scores = mad_z_scores(normalized_movements)
    latest_score = scores[-1]
    if latest_score < MAD_ANOMALY_THRESHOLD:
        return []

    latest_record = records[-1]
    if not _passes_materiality(latest_record):
        return []

    latest = latest_record["history_item"]
    # Vote-gap anomalies are statistical observations, not integrity anomalies.
    # integrity_norm=1.0 is reserved for real stable-document or acta hash changes.
    ers = compute_ers(
        stat_norm=min(latest_score / 8, 1),
        integrity_norm=0.25,
        persistence_norm=min(len([s for s in scores[-3:] if s >= 3.0]) / 3, 1),
        multi_source_norm=0.25,
        context_norm=0.45,
    )
    return [
        {
            "type": "ANOMALY_DETECTED",
            "summary": (
                "Robust MAD detector observed an unusual movement in the Keiko-Sánchez vote gap. "
                "This is non-conclusive and requires human review."
            ),
            "severity": "medium" if ers < 0.65 else "high",
            "snapshot_hash": latest["hash"],
            "sequence": latest["snapshot"]["sequence"],
            "metric": "keiko_sanchez_gap_delta",
            "value": latest_record["gap_delta"],
            "gap_delta": latest_record["gap_delta"],
            "actas_pct_delta": round(latest_record["actas_pct_delta"], 6),
            "gap_delta_per_actas_pct": round(latest_record["gap_delta_per_actas_pct"], 3),
            "direction": latest_record["direction"],
            "mad_z": round(latest_score, 3),
            "ers": ers,
        }
    ]
