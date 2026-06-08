from __future__ import annotations

from utils.snapshot_filters import filter_real_read_only_snapshots, is_real_read_only_snapshot


def _record(sequence: int, source_mode: str, collection_mode: str, source: str = "ONPE_REAL_PUBLIC_DATA") -> dict:
    return {
        "hash": f"hash-{sequence}",
        "snapshot": {
            "sequence": sequence,
            "source": source,
            "source_mode": source_mode,
            "collection_mode": collection_mode,
            "election_id": "SEP2026",
        },
    }


def test_is_real_read_only_snapshot_keeps_real_read_only_snapshot() -> None:
    assert is_real_read_only_snapshot(_record(39, "REAL_READ_ONLY", "real_read_only_public_snapshot"))


def test_is_real_read_only_snapshot_excludes_mock_snapshot() -> None:
    record = _record(38, "MOCK", "mock_passive_public_snapshot", source="MOCK_ONPE_PUBLIC_DATA")

    assert not is_real_read_only_snapshot(record)


def test_is_real_read_only_snapshot_excludes_system_frozen_freeze_and_demo_records() -> None:
    records = [
        _record(38, "REAL_READ_ONLY", "system_frozen_snapshot"),
        _record(39, "REAL_READ_ONLY", "freeze_scenario_snapshot"),
        _record(40, "REAL_READ_ONLY", "frozen_snapshot"),
        _record(41, "REAL_READ_ONLY", "demo_public_snapshot"),
    ]

    assert [is_real_read_only_snapshot(record) for record in records] == [False, False, False, False]


def test_filter_real_read_only_snapshots_excludes_seq_38_like_mock_frozen_record() -> None:
    records = [
        _record(37, "REAL_READ_ONLY", "real_read_only_public_snapshot"),
        _record(38, "MOCK", "mock_passive_public_snapshot", source="MOCK_ONPE_PUBLIC_DATA"),
        _record(39, "REAL_READ_ONLY", "real_read_only_public_snapshot"),
    ]

    filtered = filter_real_read_only_snapshots(records)

    assert [record["snapshot"]["sequence"] for record in filtered] == [37, 39]
