from __future__ import annotations

import pytest

from agents.anomaly_agent import (
    MIN_ACTAS_PCT_DELTA_FOR_ANOMALY,
    MIN_GAP_DELTA_FOR_ANOMALY,
    MIN_MOVEMENTS_FOR_MAD,
    detect_gap_anomalies,
)
from agents.evidence_agent import build_case


def _history_item(sequence: int, gap: int, actas_pct: float) -> dict:
    base_votes = 1_000_000
    return {
        "hash": f"hash-{sequence:02d}",
        "snapshot": {
            "sequence": sequence,
            "candidate_a_votes": base_votes + gap,
            "candidate_b_votes": base_votes,
            "actas_contabilizadas_pct": actas_pct,
        },
    }


def _history_from_gaps(gaps: list[int], actas_pcts: list[float]) -> list[dict]:
    return [
        _history_item(sequence=index + 1, gap=gap, actas_pct=actas_pct)
        for index, (gap, actas_pct) in enumerate(zip(gaps, actas_pcts))
    ]


def _real_history_item(sequence: int, gap: int, actas_pct: float) -> dict:
    item = _history_item(sequence, gap, actas_pct)
    item["snapshot"].update(
        {
            "source": "ONPE_REAL_PUBLIC_DATA",
            "source_mode": "REAL_READ_ONLY",
            "collection_mode": "real_read_only_public_snapshot",
            "election_id": "SEP2026",
        }
    )
    return item


def _excluded_history_item(sequence: int, gap: int, actas_pct: float) -> dict:
    item = _history_item(sequence, gap, actas_pct)
    item["snapshot"].update(
        {
            "source": "MOCK_ONPE_PUBLIC_DATA",
            "source_mode": "MOCK",
            "collection_mode": "mock_passive_public_snapshot",
            "election_id": "PER-GENERAL-MOCK-2026",
        }
    )
    return item


def test_large_negative_gap_movement_opens_case() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_200, 1_300, -11_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 74.0],
    )

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "ANOMALY_DETECTED"
    assert event["gap_delta"] == -12_600
    assert event["actas_pct_delta"] == 1.0
    assert event["gap_delta_per_actas_pct"] == -12_600.0
    assert event["direction"] == "GAP_COMPRESSED_AGAINST_LEADER"

    case = build_case(event)
    assert case["status"] == "CASE_OPENED"
    assert case["metrics"]["gap_delta"] == -12_600
    assert case["metrics"]["direction"] == "GAP_COMPRESSED_AGAINST_LEADER"


def test_large_positive_gap_movement_of_similar_magnitude_opens_case() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 900, 800, 700, 13_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 74.0],
    )

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "ANOMALY_DETECTED"
    assert event["gap_delta"] == 12_600
    assert event["gap_delta_per_actas_pct"] == 12_600.0
    assert event["direction"] == "GAP_EXPANDED_FOR_LEADER"


def test_detector_scores_are_direction_symmetric_by_magnitude() -> None:
    negative_history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_200, 1_300, -11_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 74.0],
    )
    positive_history = _history_from_gaps(
        gaps=[1_000, 900, 800, 700, 13_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 74.0],
    )

    negative_event = detect_gap_anomalies(negative_history)[0]
    positive_event = detect_gap_anomalies(positive_history)[0]

    assert abs(negative_event["gap_delta_per_actas_pct"]) == abs(
        positive_event["gap_delta_per_actas_pct"]
    )
    assert negative_event["mad_z"] == positive_event["mad_z"]


def test_duplicate_zero_delta_snapshots_do_not_distort_baseline() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_100, 1_200, 1_300, -11_300],
        actas_pcts=[70.0, 71.0, 71.0, 72.0, 73.0, 74.0],
    )

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    assert events[0]["gap_delta"] == -12_600
    assert events[0]["gap_delta_per_actas_pct"] == -12_600.0


def test_latest_duplicate_zero_delta_snapshot_is_handled_safely() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_200, 1_300, 1_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 73.0],
    )

    assert detect_gap_anomalies(history) == []


def test_latest_duplicate_after_anomaly_does_not_reemit_case() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_200, 1_300, -11_300, -11_300],
        actas_pcts=[70.0, 71.0, 72.0, 73.0, 74.0, 74.0],
    )

    assert detect_gap_anomalies(history) == []


def test_warm_up_requires_three_non_duplicate_forward_movements() -> None:
    assert MIN_MOVEMENTS_FOR_MAD == 3
    warm_up_history = _history_from_gaps(
        gaps=[1_000, 1_100, -5_000],
        actas_pcts=[70.0, 71.0, 72.0],
    )
    duplicate_reduced_history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_100, -5_000],
        actas_pcts=[70.0, 71.0, 71.0, 72.0],
    )

    assert detect_gap_anomalies(warm_up_history) == []
    assert detect_gap_anomalies(duplicate_reduced_history) == []


def test_gap_delta_per_actas_pct_normalizes_for_counting_progress() -> None:
    history = _history_from_gaps(
        gaps=[1_000, 1_100, 1_200, 1_300, -58_664],
        actas_pcts=[88.0, 89.0, 90.0, 90.742, 91.981],
    )

    event = detect_gap_anomalies(history)[0]

    assert event["gap_delta"] == -59_964
    assert event["actas_pct_delta"] == pytest.approx(1.239)
    assert event["gap_delta_per_actas_pct"] == pytest.approx(-48_397.094, abs=0.001)


def test_large_normalized_movement_with_tiny_absolute_delta_does_not_open_case() -> None:
    assert MIN_GAP_DELTA_FOR_ANOMALY == 10_000
    history = _history_from_gaps(
        gaps=[10_000, 10_100, 10_200, 10_300, 8_695],
        actas_pcts=[90.0, 91.0, 92.0, 93.0, 93.02],
    )

    assert detect_gap_anomalies(history) == []


def test_large_absolute_movement_with_sufficient_actas_delta_opens_case() -> None:
    assert MIN_ACTAS_PCT_DELTA_FOR_ANOMALY == 0.10
    history = _history_from_gaps(
        gaps=[10_000, 10_100, 10_200, 10_300, -20_000],
        actas_pcts=[90.0, 91.0, 92.0, 93.0, 93.5],
    )

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    assert events[0]["gap_delta"] == -30_300
    assert events[0]["actas_pct_delta"] == 0.5
    assert events[0]["gap_delta_per_actas_pct"] == -60_600.0


def test_seq_like_tiny_materiality_movement_is_ignored() -> None:
    history = _history_from_gaps(
        gaps=[100_000, 100_100, 100_200, 100_300, 98_695],
        actas_pcts=[88.0, 89.0, 90.0, 91.0, 91.02],
    )

    assert detect_gap_anomalies(history) == []


def test_seq_like_material_movement_can_open_case() -> None:
    history = _history_from_gaps(
        gaps=[100_000, 100_100, 100_200, 100_300, 41_336],
        actas_pcts=[88.0, 89.0, 90.0, 90.742, 91.981],
    )

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    assert events[0]["gap_delta"] == -58_964
    assert events[0]["actas_pct_delta"] == pytest.approx(1.239)
    assert events[0]["gap_delta_per_actas_pct"] == pytest.approx(-47_590.0, abs=0.01)


def test_anomaly_baseline_excludes_contaminated_mock_snapshot_between_real_records() -> None:
    history = [
        _real_history_item(35, 1_000, 70.0),
        _real_history_item(36, 1_100, 71.0),
        _excluded_history_item(38, 1_000_000, 100.0),
        _real_history_item(39, 1_200, 72.0),
        _real_history_item(40, -11_300, 73.0),
    ]

    events = detect_gap_anomalies(history)

    assert len(events) == 1
    assert events[0]["sequence"] == 40
    assert events[0]["gap_delta"] == -12_500
    assert events[0]["actas_pct_delta"] == 1.0


def test_excluded_latest_snapshot_does_not_reemit_previous_real_anomaly() -> None:
    history = [
        _real_history_item(35, 1_000, 70.0),
        _real_history_item(36, 1_100, 71.0),
        _real_history_item(37, 1_200, 72.0),
        _real_history_item(39, -11_300, 73.0),
        _excluded_history_item(38, 1_000_000, 100.0),
    ]

    assert detect_gap_anomalies(history) == []
