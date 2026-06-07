from __future__ import annotations

from typing import Any

from models.ers import compute_ers
from models.mad import mad_z_scores


def _vote_gap(snapshot: dict[str, Any]) -> int:
    if "candidate_a_votes" in snapshot and "candidate_b_votes" in snapshot:
        return int(snapshot["candidate_a_votes"] - snapshot["candidate_b_votes"])
    totals = snapshot.get("national_totals", {})
    return int(totals.get("candidate_a_votes", 0) - totals.get("candidate_b_votes", 0))


def detect_gap_anomalies(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(history) < 4:
        return []
    gaps = [_vote_gap(item["snapshot"]) for item in history]
    deltas = [current - previous for previous, current in zip(gaps, gaps[1:])]
    scores = mad_z_scores(deltas)
    latest_score = scores[-1]
    if latest_score < 3.5:
        return []

    latest = history[-1]
    ers = compute_ers(
        stat_norm=min(latest_score / 8, 1),
        integrity_norm=1.0,
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
            "value": deltas[-1],
            "mad_z": round(latest_score, 3),
            "ers": ers,
        }
    ]
