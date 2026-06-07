from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from agents.anomaly_agent import detect_gap_anomalies
from agents.evidence_agent import build_case, case_events
from agents.integrity_agent import integrity_events, integrity_status, snapshot_hash
from agents.onpe_agent import select_onpe_snapshot_source
from config import (
    CANDIDATE_A_NAME,
    CANDIDATE_B_NAME,
    CASES_PATH,
    DISCLAIMER_LINES,
    EVENTS_PATH,
    FREEZE_THRESHOLD_PCT,
    REAL_ONPE_ENABLED,
    REAL_SOURCE_STATUS,
    REAL_SOURCE_STATUS_NOTE,
    SNAPSHOTS_PATH,
    SOURCE_MODE,
)
from storage.json_store import append_jsonl, read_jsonl
from ui.case_view import render_case_view
from ui.electoral_behavior import render_electoral_behavior
from ui.integrity_view import render_integrity_view
from ui.soc_feed import render_soc_feed


def _event_record(event: dict, captured_at: str) -> dict:
    record = dict(event)
    record["captured_at"] = captured_at
    return record


def capture_cycle(force: bool = False) -> None:
    if SOURCE_MODE == "REAL_READ_ONLY" and not REAL_ONPE_ENABLED:
        st.warning("REAL_READ_ONLY está configurado, pero el conector real ONPE está desactivado.")
        return
    try:
        snapshot = select_onpe_snapshot_source(force=force)
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    digest = snapshot_hash(snapshot)
    snapshot["snapshot_hash"] = digest
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshots = read_jsonl(SNAPSHOTS_PATH)
    if snapshots and snapshots[-1]["hash"] == digest:
        return

    artifact_type = "aggregate_snapshot"
    previous_digest = snapshots[-1]["hash"] if snapshots else None
    status = integrity_status(artifact_type, digest, previous_digest)
    snapshot_record = {
        "captured_at": captured_at,
        "hash": digest,
        "snapshot_hash": digest,
        "artifact_type": artifact_type,
        "integrity_status": status,
        "snapshot": snapshot,
    }
    append_jsonl(SNAPSHOTS_PATH, snapshot_record)
    snapshots.append(snapshot_record)

    events = integrity_events(snapshot, digest, previous_digest, artifact_type=artifact_type)
    events.extend(detect_gap_anomalies(snapshots))
    for event in events:
        append_jsonl(EVENTS_PATH, _event_record(event, captured_at))
        if event["type"] == "ANOMALY_DETECTED":
            case = build_case(event)
            append_jsonl(CASES_PATH, case)
            for case_event in case_events(case):
                append_jsonl(EVENTS_PATH, _event_record(case_event, captured_at))


def generate_mock_snapshots(count: int = 12) -> None:
    for _ in range(count):
        capture_cycle(force=True)


def generate_freeze_scenario(max_snapshots: int = 24) -> None:
    for _ in range(max_snapshots):
        snapshots = read_jsonl(SNAPSHOTS_PATH)
        latest = snapshots[-1]["snapshot"] if snapshots else None
        if latest and latest["actas_contabilizadas_pct"] >= FREEZE_THRESHOLD_PCT:
            break
        capture_cycle(force=True)


def _render_disclaimers() -> None:
    for line in DISCLAIMER_LINES:
        st.caption(line)
    st.caption("Comportamiento observado desde snapshots capturados.")
    st.caption("Una anomalía estadística solo indica movimiento inusual que requiere revisión.")


def _render_overview(snapshots: list[dict], cases: list[dict], events: list[dict]) -> None:
    st.subheader("Resumen Operativo")
    latest = snapshots[-1]["snapshot"] if snapshots else None
    last_pct = latest["actas_contabilizadas_pct"] if latest else 0.0
    system_status = "FROZEN" if latest and last_pct >= FREEZE_THRESHOLD_PCT else "ACTIVE"
    last_sequence = latest["sequence"] if latest else "-"
    columns = st.columns(6)
    columns[0].metric("Estado del sistema", system_status)
    columns[1].metric("Último % de actas", f"{last_pct}%" if latest else "0%")
    columns[2].metric("Última secuencia", last_sequence)
    columns[3].metric("Snapshots", len(snapshots))
    columns[4].metric("Eventos", len(events))
    columns[5].metric("Casos de evidencia", len(cases))
    with st.container(border=True):
        st.markdown("**Estado de fuente oficial**")
        st.write(
            "La fuente pública de segunda vuelta aún no está confirmada. "
            "El sistema opera en modo MOCK y no interpreta datos de primera vuelta como datos de segunda vuelta."
        )
    if latest:
        candidate_a_votes = latest.get("candidate_a_votes", latest.get("national_totals", {}).get("candidate_a_votes", 0))
        candidate_b_votes = latest.get("candidate_b_votes", latest.get("national_totals", {}).get("candidate_b_votes", 0))
        vote_gap_abs = latest.get("vote_gap_abs", abs(candidate_a_votes - candidate_b_votes))
        vote_gap_pct = latest.get("vote_gap_pct", 0.0)
        kpi_columns = st.columns(4)
        kpi_columns[0].metric(f"{CANDIDATE_A_NAME} votes", f"{candidate_a_votes:,}")
        kpi_columns[1].metric(f"{CANDIDATE_B_NAME} votes", f"{candidate_b_votes:,}")
        kpi_columns[2].metric("Keiko - Sánchez gap", f"{vote_gap_abs:,}")
        kpi_columns[3].metric("Vote gap pct", f"{vote_gap_pct}%")

        gap_frame = pd.DataFrame(
            [
                {
                    "snapshot": item["snapshot"]["sequence"],
                    "Keiko - Sánchez gap": item["snapshot"].get(
                        "vote_gap_abs",
                        abs(
                            item["snapshot"].get("candidate_a_votes", 0)
                            - item["snapshot"].get("candidate_b_votes", 0)
                        ),
                    ),
                }
                for item in snapshots
            ]
        )
        st.line_chart(gap_frame, x="snapshot", y="Keiko - Sánchez gap")
        pct_frame = pd.DataFrame(
            [
                {
                    "snapshot": item["snapshot"]["sequence"],
                    CANDIDATE_A_NAME: item["snapshot"].get("candidate_a_pct", 0.0),
                    CANDIDATE_B_NAME: item["snapshot"].get("candidate_b_pct", 0.0),
                }
                for item in snapshots
            ]
        )
        st.line_chart(pct_frame, x="snapshot", y=[CANDIDATE_A_NAME, CANDIDATE_B_NAME])
        st.progress(min(latest["actas_contabilizadas_pct"] / FREEZE_THRESHOLD_PCT, 1.0))
        st.write(
            {
                "source": latest["source"],
                "source_mode": latest.get("source_mode", "MOCK"),
                f"{CANDIDATE_A_NAME} votes": candidate_a_votes,
                f"{CANDIDATE_B_NAME} votes": candidate_b_votes,
                "Keiko - Sánchez gap": vote_gap_abs,
                "Vote gap pct": vote_gap_pct,
                "latest_hash": snapshots[-1]["hash"],
            }
        )


def _render_methodology() -> None:
    st.subheader("Methodology")
    st.markdown(
        """
- Collection: deterministic mock public-data snapshots only. SOURCE_MODE defaults to MOCK. Real ONPE endpoints are intentionally not called in this MVP.
- No se realizan llamadas reales a ONPE.
- La fuente real permanece desactivada hasta que ONPE publique una ruta pública estable de segunda vuelta.
- El sistema no infiere datos reales desde portales de primera vuelta ni endpoints históricos.
- Integrity: every raw snapshot is canonicalized and hashed with SHA-256 for reproducibility. Aggregate snapshot hash changes are expected as counting progresses.
- Document hash alerts: DOCUMENT_HASH_CHANGED is reserved for stable documents or actas whose content hash changes across captures.
- Eventos: SNAPSHOT_CAPTURED, DOCUMENT_HASH_CHANGED, ANOMALY_DETECTED, CASE_OPENED, CASE_EXPLAINED, CASE_CLOSED and SYSTEM_FROZEN.
- Case lifecycle: CASE_EXPLAINED and CASE_CLOSED are emitted only after explicit human review actions.
- Statistics: robust MAD detection over vote-gap evolution.
- ERS: 0.30*Stat_norm + 0.25*Integrity_norm + 0.20*Persistence_norm + 0.15*MultiSource_norm + 0.10*Context_norm.
- Confidence: source official, hash+snapshot, reproducibility, human review and multi-artifact consistency.
- Evidence: E0-E5 levels describe evidence completeness, not intent or legal conclusions.
- Candidate labels: mock runoff snapshots use Keiko Fujimori and Roberto Sánchez for local testing only.
        """
    )


def render_dashboard() -> None:
    st.title("Personero Digital")
    _render_disclaimers()
    with st.sidebar:
        st.header("Controls")
        st.caption(f"Fuente de datos: {SOURCE_MODE}")
        st.caption(f"Estado fuente real ONPE: {REAL_SOURCE_STATUS}")
        st.caption("Nota: portal público de segunda vuelta aún no disponible para resultados.")
        st.caption(REAL_SOURCE_STATUS_NOTE)
        if st.button("Capture mock snapshot", type="primary"):
            capture_cycle(force=True)
            st.rerun()
        if st.button("Use cache-aware capture"):
            capture_cycle(force=False)
            st.rerun()
        if st.button("Generate 12 mock snapshots"):
            generate_mock_snapshots(12)
            st.rerun()
        if st.button("Generate freeze scenario"):
            generate_freeze_scenario()
            st.rerun()

    snapshots = read_jsonl(SNAPSHOTS_PATH)
    events = read_jsonl(EVENTS_PATH)
    cases = read_jsonl(CASES_PATH)

    tabs = st.tabs(["Overview", "Comportamiento Electoral", "SOC Feed", "Integrity", "Cases", "Methodology"])
    with tabs[0]:
        _render_overview(snapshots, cases, events)
    with tabs[1]:
        render_electoral_behavior(snapshots, events, cases)
    with tabs[2]:
        render_soc_feed(events)
    with tabs[3]:
        render_integrity_view(snapshots, events)
    with tabs[4]:
        render_case_view(cases)
    with tabs[5]:
        _render_methodology()
