from __future__ import annotations

from ui.electoral_behavior import (
    build_gap_evolution_df,
    build_vote_pct_long_df,
    filter_real_behavior_snapshots,
)


def _snapshot_record(
    sequence: int,
    source_mode: str,
    collection_mode: str,
    candidate_a_pct: float = 50.125,
    candidate_b_pct: float = 49.875,
    vote_gap_abs: int = 43_624,
) -> dict:
    return {
        "hash": f"hash-{sequence}",
        "snapshot_hash": f"hash-{sequence}",
        "snapshot": {
            "sequence": sequence,
            "captured_at": "2026-06-08T12:52:11.937528+00:00",
            "actas_contabilizadas_pct": 92.797,
            "candidate_a_name": "Keiko Fujimori",
            "candidate_a_pct": candidate_a_pct,
            "candidate_a_votes": 8_740_160,
            "candidate_b_name": "Roberto Sánchez",
            "candidate_b_pct": candidate_b_pct,
            "candidate_b_votes": 8_696_536,
            "vote_gap_abs": vote_gap_abs,
            "vote_gap_pct": round(candidate_a_pct - candidate_b_pct, 3),
            "source": "ONPE_REAL_PUBLIC_DATA" if source_mode == "REAL_READ_ONLY" else "MOCK_ONPE_PUBLIC_DATA",
            "source_mode": source_mode,
            "collection_mode": collection_mode,
            "snapshot_hash": f"snapshot-hash-{sequence}",
        },
    }


def test_filter_real_behavior_snapshots_keeps_real_read_only_records() -> None:
    records = [
        _snapshot_record(39, "REAL_READ_ONLY", "real_read_only_public_snapshot"),
        _snapshot_record(40, "REAL_READ_ONLY", "real_read_only_public_snapshot", vote_gap_abs=43_425),
    ]

    filtered = filter_real_behavior_snapshots(records)

    assert [snapshot["sequence"] for snapshot in filtered] == [39, 40]


def test_filter_real_behavior_snapshots_excludes_sequence_38_like_mock_record() -> None:
    records = [
        _snapshot_record(38, "MOCK", "mock_passive_public_snapshot", vote_gap_abs=443),
        _snapshot_record(39, "REAL_READ_ONLY", "real_read_only_public_snapshot"),
    ]

    filtered = filter_real_behavior_snapshots(records)

    assert [snapshot["sequence"] for snapshot in filtered] == [39]


def test_filter_real_behavior_snapshots_excludes_demo_or_freeze_records() -> None:
    records = [
        _snapshot_record(37, "REAL_READ_ONLY", "real_read_only_public_snapshot"),
        _snapshot_record(38, "REAL_READ_ONLY", "demo_freeze_snapshot"),
        _snapshot_record(39, "REAL_READ_ONLY", "system_frozen_snapshot"),
    ]

    filtered = filter_real_behavior_snapshots(records)

    assert [snapshot["sequence"] for snapshot in filtered] == [37]


def test_build_vote_pct_long_df_uses_candidate_a_and_candidate_b_schema() -> None:
    snapshots = filter_real_behavior_snapshots(
        [
            _snapshot_record(
                39,
                "REAL_READ_ONLY",
                "real_read_only_public_snapshot",
                candidate_a_pct=50.125,
                candidate_b_pct=49.875,
            )
        ]
    )

    frame = build_vote_pct_long_df(snapshots)

    assert frame.to_dict("records") == [
        {"sequence": 39, "candidate": "Keiko Fujimori", "vote_pct": 50.125},
        {"sequence": 39, "candidate": "Roberto Sánchez", "vote_pct": 49.875},
    ]


def test_build_gap_evolution_df_preserves_vote_gap_abs() -> None:
    snapshots = filter_real_behavior_snapshots(
        [
            _snapshot_record(39, "REAL_READ_ONLY", "real_read_only_public_snapshot", vote_gap_abs=43_624),
            _snapshot_record(40, "REAL_READ_ONLY", "real_read_only_public_snapshot", vote_gap_abs=43_425),
        ]
    )

    frame = build_gap_evolution_df(snapshots)

    assert frame[["sequence", "vote_gap_abs"]].to_dict("records") == [
        {"sequence": 39, "vote_gap_abs": 43_624},
        {"sequence": 40, "vote_gap_abs": 43_425},
    ]
