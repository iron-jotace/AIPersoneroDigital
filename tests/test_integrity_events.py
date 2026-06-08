from __future__ import annotations

from agents.integrity_agent import integrity_events


def _snapshot(**overrides: object) -> dict:
    snapshot = {
        "sequence": 1,
        "actas_contabilizadas_pct": 50.0,
        "source": "UNKNOWN",
        "source_mode": "UNKNOWN",
    }
    snapshot.update(overrides)
    return snapshot


def _snapshot_captured_summary(snapshot: dict) -> str:
    events = integrity_events(snapshot, "abc123", previous_digest=None)
    return events[0]["summary"]


def test_mock_snapshot_produces_mock_summary() -> None:
    summary = _snapshot_captured_summary(
        _snapshot(source="MOCK_ONPE_PUBLIC_DATA", source_mode="MOCK")
    )

    assert summary == "Snapshot mock capturado y hasheado."


def test_real_onpe_snapshot_produces_read_only_summary() -> None:
    summary = _snapshot_captured_summary(
        _snapshot(source="ONPE_REAL_PUBLIC_DATA", source_mode="REAL_READ_ONLY")
    )

    assert summary == "Snapshot público ONPE en modo solo lectura capturado y hasheado."


def test_unknown_source_produces_generic_public_summary() -> None:
    summary = _snapshot_captured_summary(_snapshot(source="OTHER_PUBLIC_SOURCE"))

    assert summary == "Snapshot público capturado y hasheado."
