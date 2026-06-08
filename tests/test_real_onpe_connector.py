from __future__ import annotations

import pytest

import agents.onpe_agent as onpe_agent


PROCESS_RESPONSE = {
    "success": True,
    "data": {
        "nombre": "SEGUNDA ELECCION PRESIDENCIAL 2026",
        "acronimo": "SEP2026",
        "idEleccionPrincipal": 10,
    },
}

TOTALS_RESPONSE = {
    "success": True,
    "data": {
        "actasContabilizadas": 42.5,
        "contabilizadas": 4250,
        "totalActas": 10000,
        "totalVotosValidos": 1000000,
        "totalVotosEmitidos": 1030000,
        "fechaActualizacion": "2026-06-08T12:00:00",
    },
}

PARTICIPANTS_RESPONSE = {
    "success": True,
    "data": [
        {
            "nombreCandidato": "ROBERTO HELBERT SANCHEZ PALOMINO",
            "totalVotosValidos": 490000,
            "porcentajeVotosValidos": 49.0,
        },
        {
            "nombreCandidato": "KEIKO SOFIA FUJIMORI HIGUCHI",
            "totalVotosValidos": 510000,
            "porcentajeVotosValidos": 51.0,
        },
    ],
}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, params: dict | None = None, timeout: int = 15) -> FakeResponse:
        if url.endswith(onpe_agent.ONPE_PROCESS_ENDPOINT):
            return FakeResponse(PROCESS_RESPONSE)
        if url.endswith(onpe_agent.ONPE_TOTALS_ENDPOINT):
            return FakeResponse(TOTALS_RESPONSE)
        if url.endswith(onpe_agent.ONPE_PARTICIPANTS_ENDPOINT):
            return FakeResponse(PARTICIPANTS_RESPONSE)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _enable_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "REAL_ONPE_ENABLED", True)
    monkeypatch.setattr(onpe_agent, "SOURCE_MODE", "REAL_READ_ONLY")
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "transparent")
    monkeypatch.setattr(onpe_agent, "_next_sequence_from_bronze", lambda: 1)
    monkeypatch.setattr(onpe_agent.requests, "Session", FakeSession)
    onpe_agent._REAL_SNAPSHOT_CACHE["fetched_at_epoch"] = 0.0
    onpe_agent._REAL_SNAPSHOT_CACHE["snapshot"] = None


def test_transparent_profile_uses_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "transparent")

    headers = onpe_agent._onpe_headers()

    assert headers["User-Agent"] == onpe_agent.USER_AGENT


def test_transparent_profile_does_not_include_sec_fetch_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "transparent")

    headers = onpe_agent._onpe_headers()

    assert "Sec-Fetch-Dest" not in headers
    assert "Sec-Fetch-Mode" not in headers
    assert "Sec-Fetch-Site" not in headers


def test_browser_observed_profile_uses_browser_observed_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "browser_observed")

    headers = onpe_agent._onpe_headers()

    assert headers["User-Agent"] == onpe_agent.ONPE_BROWSER_OBSERVED_USER_AGENT


def test_browser_observed_profile_includes_sec_fetch_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "browser_observed")

    headers = onpe_agent._onpe_headers()

    assert headers["Sec-Fetch-Dest"] == "empty"
    assert headers["Sec-Fetch-Mode"] == "cors"
    assert headers["Sec-Fetch-Site"] == "same-origin"


def test_onpe_headers_never_include_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    for profile in ["transparent", "browser_observed"]:
        monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", profile)

        assert "Cookie" not in onpe_agent._onpe_headers()


def test_invalid_onpe_http_profile_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "ONPE_HTTP_PROFILE", "invalid")

    with pytest.raises(ValueError):
        onpe_agent._onpe_headers()


def test_real_connector_rejects_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onpe_agent, "REAL_ONPE_ENABLED", False)

    with pytest.raises(RuntimeError, match="disabled"):
        onpe_agent.fetch_real_onpe_snapshot(force=True)


def test_real_connector_rejects_when_source_mode_is_not_real_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onpe_agent, "REAL_ONPE_ENABLED", True)
    monkeypatch.setattr(onpe_agent, "SOURCE_MODE", "MOCK")

    with pytest.raises(RuntimeError, match="SOURCE_MODE"):
        onpe_agent.fetch_real_onpe_snapshot(force=True)


def test_real_connector_validates_second_round_process(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_real_mode(monkeypatch)

    snapshot = onpe_agent.fetch_real_onpe_snapshot(force=True)

    assert snapshot["election_id"] == "SEP2026"
    assert snapshot["source_mode"] == "REAL_READ_ONLY"


def test_real_connector_maps_candidates_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_real_mode(monkeypatch)

    snapshot = onpe_agent.fetch_real_onpe_snapshot(force=True)

    assert snapshot["candidate_a_name"] == "Keiko Fujimori"
    assert snapshot["candidate_a_votes"] == 510000
    assert snapshot["candidate_a_pct"] == 51.0
    assert snapshot["candidate_b_name"] == "Roberto Sánchez"
    assert snapshot["candidate_b_votes"] == 490000
    assert snapshot["candidate_b_pct"] == 49.0


def test_real_connector_computes_vote_gap_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_real_mode(monkeypatch)

    snapshot = onpe_agent.fetch_real_onpe_snapshot(force=True)

    assert snapshot["vote_gap_abs"] == 20000
    assert snapshot["vote_gap_pct"] == 2.0
