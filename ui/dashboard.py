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
    ONPE_HTTP_PROFILE,
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


def capture_cycle(force: bool = False) -> bool:
    if SOURCE_MODE == "REAL_READ_ONLY" and not REAL_ONPE_ENABLED:
        st.warning("REAL_READ_ONLY está configurado, pero el conector real ONPE está desactivado.")
        return False
    try:
        snapshot = select_onpe_snapshot_source(force=force)
    except RuntimeError as exc:
        st.warning(str(exc))
        return False
    digest = snapshot_hash(snapshot)
    snapshot.setdefault("snapshot_hash", digest)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshots = read_jsonl(SNAPSHOTS_PATH)
    if snapshots and snapshots[-1]["hash"] == digest:
        return False

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
    return True


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


def _capture_button_label() -> str:
    if SOURCE_MODE == "MOCK":
        return "Capturar snapshot mock"
    if SOURCE_MODE == "REAL_READ_ONLY":
        return "Capturar snapshot ONPE real"
    return "Capturar snapshot"


def _capture_success_message() -> str:
    if SOURCE_MODE == "MOCK":
        return "Snapshot mock capturado."
    if SOURCE_MODE == "REAL_READ_ONLY":
        return "Snapshot ONPE real capturado en modo solo lectura."
    return "Snapshot capturado."


def _official_source_status_text() -> str:
    if SOURCE_MODE == "MOCK":
        return "El sistema opera en modo MOCK. No se están capturando datos reales de ONPE."
    if SOURCE_MODE == "REAL_READ_ONLY":
        return (
            "El sistema opera en modo REAL_READ_ONLY. Solo captura datos públicos oficiales de ONPE, "
            "sin modificar fuentes externas."
        )
    return f"El sistema opera en modo {SOURCE_MODE}."


def _render_overview(snapshots: list[dict], cases: list[dict], events: list[dict]) -> None:
    st.subheader("Resumen Operativo")
    latest = snapshots[-1]["snapshot"] if snapshots else None
    last_pct = latest["actas_contabilizadas_pct"] if latest else 0.0
    system_status = "CONGELADO" if latest and last_pct >= FREEZE_THRESHOLD_PCT else "ACTIVO"
    last_sequence = latest["sequence"] if latest else "-"
    columns = st.columns(6)
    columns[0].metric("Estado del sistema", system_status)
    columns[1].metric("Último % de actas", f"{last_pct}%" if latest else "0%")
    columns[2].metric("Última secuencia", last_sequence)
    columns[3].metric("Capturas", len(snapshots))
    columns[4].metric("Eventos", len(events))
    columns[5].metric("Casos de evidencia", len(cases))
    with st.container(border=True):
        st.markdown("**Estado de fuente oficial**")
        st.write(_official_source_status_text())
    if latest:
        candidate_a_votes = latest.get("candidate_a_votes", latest.get("national_totals", {}).get("candidate_a_votes", 0))
        candidate_b_votes = latest.get("candidate_b_votes", latest.get("national_totals", {}).get("candidate_b_votes", 0))
        vote_gap_abs = latest.get("vote_gap_abs", abs(candidate_a_votes - candidate_b_votes))
        vote_gap_pct = latest.get("vote_gap_pct", 0.0)
        kpi_columns = st.columns(4)
        kpi_columns[0].metric("Votos Keiko Fujimori", f"{candidate_a_votes:,}")
        kpi_columns[1].metric("Votos Roberto Sánchez", f"{candidate_b_votes:,}")
        kpi_columns[2].metric("Keiko - Sánchez gap", f"{vote_gap_abs:,}")
        kpi_columns[3].metric("% brecha de votos", f"{vote_gap_pct}%")

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
                "Votos Keiko Fujimori": candidate_a_votes,
                "Votos Roberto Sánchez": candidate_b_votes,
                "Keiko - Sánchez gap": vote_gap_abs,
                "% brecha de votos": vote_gap_pct,
                "latest_hash": snapshots[-1]["hash"],
            }
        )


def _render_methodology() -> None:
    st.subheader("Metodología")
    st.markdown(
        """
- Recolección: snapshots mock determinísticos de datos públicos. SOURCE_MODE permanece en MOCK por defecto. En este MVP no se llaman endpoints reales de ONPE.
- En modo MOCK no se realizan llamadas reales a ONPE.
- El conector REAL_READ_ONLY permanece desactivado por defecto y solo se activa mediante configuración explícita.
- La fuente pública oficial de segunda vuelta fue validada mediante endpoints públicos observados desde el navegador.
- El sistema no infiere datos reales desde portales de primera vuelta ni endpoints históricos.
- El modo REAL_READ_ONLY solo se activa mediante configuración explícita.
- El conector real usa únicamente endpoints públicos observados desde el navegador.
- No se usan cookies, tokens ni autenticación.
- El perfil browser_observed existe porque ONPE/CloudFront puede devolver HTML fallback con el User-Agent transparente.
- Una anomalía no implica fraude.
- Toda alerta requiere revisión humana.
- Integridad: cada snapshot crudo se canonicaliza y se resume con SHA-256 para reproducibilidad. Los cambios de hash en snapshots agregados son esperados durante el avance del conteo.
- Alertas de hash documental: DOCUMENT_HASH_CHANGED se reserva para documentos estables o actas cuyo hash de contenido cambia entre capturas.
- Eventos: SNAPSHOT_CAPTURED, DOCUMENT_HASH_CHANGED, ANOMALY_DETECTED, CASE_OPENED, CASE_EXPLAINED, CASE_CLOSED y SYSTEM_FROZEN.
- Ciclo de vida de casos: CASE_EXPLAINED y CASE_CLOSED solo se emiten después de acciones explícitas de revisión humana.
- Estadística: detección robusta MAD sobre la evolución de la brecha de votos.
- ERS: 0.30*Stat_norm + 0.25*Integrity_norm + 0.20*Persistence_norm + 0.15*MultiSource_norm + 0.10*Context_norm.
- Confianza: fuente oficial, hash+snapshot, reproducibilidad, revisión humana y consistencia multiartefacto.
- Evidencia: los niveles E0-E5 describen completitud de evidencia, no intenciones ni conclusiones legales.
- Etiquetas de candidatos: los snapshots mock de segunda vuelta usan Keiko Fujimori y Roberto Sánchez solo para pruebas locales.
        """
    )


def render_dashboard() -> None:
    st.title("Personero Digital")
    _render_disclaimers()
    with st.sidebar:
        st.header("Controles")
        st.caption(f"Fuente de datos: {SOURCE_MODE}")
        st.caption(f"Estado fuente real ONPE: {REAL_SOURCE_STATUS}")
        st.caption(f"Perfil HTTP ONPE: {ONPE_HTTP_PROFILE}")
        st.caption(f"Real ONPE habilitado: {REAL_ONPE_ENABLED}")
        st.caption(REAL_SOURCE_STATUS_NOTE)
        if "capture_success_message" in st.session_state:
            st.success(st.session_state.pop("capture_success_message"))
        if st.button(_capture_button_label(), type="primary"):
            if capture_cycle(force=True):
                st.session_state["capture_success_message"] = _capture_success_message()
            st.rerun()
        if st.button("Captura con caché"):
            capture_cycle(force=False)
            st.rerun()
        if st.button("Generar 12 snapshots mock"):
            generate_mock_snapshots(12)
            st.rerun()
        if st.button("Generar escenario de congelación"):
            generate_freeze_scenario()
            st.rerun()

    snapshots = read_jsonl(SNAPSHOTS_PATH)
    events = read_jsonl(EVENTS_PATH)
    cases = read_jsonl(CASES_PATH)

    tabs = st.tabs(["Resumen", "Comportamiento Electoral", "Feed SOC", "Integridad", "Casos", "Metodología"])
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
