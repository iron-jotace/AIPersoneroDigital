from __future__ import annotations

import copy

import ui.dashboard as dashboard


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict = {}
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def _snapshot(
    sequence: int,
    *,
    actas_pct: float = 93.092,
    candidate_a_votes: int = 8_752_752,
    candidate_b_votes: int = 8_724_815,
    candidate_a_pct: float = 50.08,
    candidate_b_pct: float = 49.92,
) -> dict:
    return {
        "source": "ONPE_REAL_PUBLIC_DATA",
        "source_url": "https://resultadosegundavuelta.onpe.gob.pe/main/resumen",
        "source_mode": "REAL_READ_ONLY",
        "collection_mode": "real_read_only_public_snapshot",
        "artifact_type": "aggregate_snapshot",
        "sequence": sequence,
        "captured_at": f"2026-06-08T13:{sequence:02d}:00+00:00",
        "captured_at_utc": f"2026-06-08T13:{sequence:02d}:00+00:00",
        "election_id": "SEP2026",
        "candidate_a_name": "Keiko Fujimori",
        "candidate_b_name": "Roberto Sánchez",
        "candidate_a_votes": candidate_a_votes,
        "candidate_b_votes": candidate_b_votes,
        "candidate_a_pct": candidate_a_pct,
        "candidate_b_pct": candidate_b_pct,
        "vote_gap_abs": candidate_a_votes - candidate_b_votes,
        "vote_gap_pct": round(candidate_a_pct - candidate_b_pct, 3),
        "actas_contabilizadas_pct": actas_pct,
        "actas_contabilizadas": 86_358,
        "total_actas": 92_766,
        "total_votos_validos": candidate_a_votes + candidate_b_votes,
        "total_votos_emitidos": candidate_a_votes + candidate_b_votes + 1_200_000,
        "fecha_actualizacion_onpe": "2026-06-08T13:54:00",
    }


def _install_capture_harness(monkeypatch, initial_snapshots: list[dict] | None = None) -> dict:
    fake_st = FakeStreamlit()
    stores = {
        dashboard.SNAPSHOTS_PATH: list(initial_snapshots or []),
        dashboard.EVENTS_PATH: [],
        dashboard.CASES_PATH: [],
    }

    monkeypatch.setattr(dashboard, "st", fake_st)
    monkeypatch.setattr(dashboard, "SOURCE_MODE", "REAL_READ_ONLY")
    monkeypatch.setattr(dashboard, "REAL_ONPE_ENABLED", True)
    monkeypatch.setattr(dashboard, "detect_gap_anomalies", lambda _snapshots: [])

    def fake_read_jsonl(path):
        return copy.deepcopy(stores.setdefault(path, []))

    def fake_append_jsonl(path, item):
        stores.setdefault(path, []).append(copy.deepcopy(item))

    monkeypatch.setattr(dashboard, "read_jsonl", fake_read_jsonl)
    monkeypatch.setattr(dashboard, "append_jsonl", fake_append_jsonl)
    return stores


def _snapshot_record(snapshot: dict) -> dict:
    digest = dashboard.snapshot_hash(snapshot)
    return {
        "captured_at": snapshot["captured_at"],
        "hash": digest,
        "content_hash": dashboard.snapshot_content_hash(snapshot),
        "snapshot_hash": digest,
        "artifact_type": "aggregate_snapshot",
        "integrity_status": "EXPECTED_CHANGE",
        "snapshot": copy.deepcopy(snapshot),
    }


def test_changed_actas_pct_creates_new_snapshot(monkeypatch) -> None:
    previous = _snapshot(42, actas_pct=93.092)
    stores = _install_capture_harness(monkeypatch, [_snapshot_record(previous)])
    next_snapshot = _snapshot(43, actas_pct=93.397)
    monkeypatch.setattr(dashboard, "select_onpe_snapshot_source", lambda force=False: copy.deepcopy(next_snapshot))

    result = dashboard.capture_cycle(force=True)

    assert result == "captured"
    assert len(stores[dashboard.SNAPSHOTS_PATH]) == 2
    assert stores[dashboard.SNAPSHOTS_PATH][-1]["snapshot"]["actas_contabilizadas_pct"] == 93.397


def test_changed_candidate_votes_creates_new_snapshot(monkeypatch) -> None:
    previous = _snapshot(42, candidate_a_votes=8_752_752, candidate_b_votes=8_724_815)
    stores = _install_capture_harness(monkeypatch, [_snapshot_record(previous)])
    next_snapshot = _snapshot(43, candidate_a_votes=8_765_154, candidate_b_votes=8_749_850)
    monkeypatch.setattr(dashboard, "select_onpe_snapshot_source", lambda force=False: copy.deepcopy(next_snapshot))

    result = dashboard.capture_cycle(force=True)

    assert result == "captured"
    assert len(stores[dashboard.SNAPSHOTS_PATH]) == 2
    assert stores[dashboard.SNAPSHOTS_PATH][-1]["snapshot"]["candidate_a_votes"] == 8_765_154
    assert stores[dashboard.SNAPSHOTS_PATH][-1]["snapshot"]["vote_gap_abs"] == 15_304


def test_identical_extracted_payload_does_not_create_duplicate_snapshot(monkeypatch) -> None:
    previous = _snapshot(42)
    stores = _install_capture_harness(monkeypatch, [_snapshot_record(previous)])
    same_content = _snapshot(43)
    monkeypatch.setattr(dashboard, "select_onpe_snapshot_source", lambda force=False: copy.deepcopy(same_content))

    result = dashboard.capture_cycle(force=True)

    assert result == "unchanged"
    assert len(stores[dashboard.SNAPSHOTS_PATH]) == 1
    assert dashboard.LAST_CAPTURE_DEBUG["duplicate"] is True


def test_forced_capture_bypasses_interval_guard_and_local_cache(monkeypatch) -> None:
    stores = _install_capture_harness(monkeypatch)
    calls: list[bool] = []

    def fake_select(force: bool = False) -> dict:
        calls.append(force)
        return _snapshot(1)

    monkeypatch.setattr(dashboard, "select_onpe_snapshot_source", fake_select)

    result = dashboard.capture_cycle(force=True)

    assert result == "captured"
    assert calls == [True]
    assert len(stores[dashboard.SNAPSHOTS_PATH]) == 1
    assert dashboard.LAST_CAPTURE_DEBUG["cache_bypassed"] is True
