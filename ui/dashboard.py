from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
import streamlit as st

from agents.anomaly_agent import detect_gap_anomalies
from agents.evidence_agent import build_case, case_events
from agents.integrity_agent import integrity_events, integrity_status, snapshot_content_hash, snapshot_hash
from agents.onpe_agent import select_onpe_snapshot_source
from config import (
    APP_NAME,
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

CaptureResult = Literal["captured", "unchanged", "failed"]
AUTO_CAPTURE_INTERVALS = [300, 600, 900]
AUTO_CAPTURE_RERUN_SECONDS = 30
LOGGER = logging.getLogger(__name__)
LAST_CAPTURE_DEBUG: dict = {}


def _startup_log(message: str) -> None:
    print(message, flush=True)


def _running_as_streamlit_entrypoint() -> bool:
    return any(Path(arg).as_posix().endswith("ui/dashboard.py") for arg in sys.argv)


def _event_record(event: dict, captured_at: str) -> dict:
    record = dict(event)
    record["captured_at"] = captured_at
    return record


def _capture_debug_payload(
    snapshot: dict,
    *,
    force: bool,
    result: CaptureResult,
    duplicate: bool,
    latest_persisted_sequence: int | str,
) -> dict:
    return {
        "source": snapshot.get("source"),
        "source_mode": snapshot.get("source_mode"),
        "source_url": snapshot.get("source_url"),
        "http_profile": ONPE_HTTP_PROFILE,
        "cache_bypassed": force,
        "actas_pct": snapshot.get("actas_contabilizadas_pct"),
        "candidate_a_votes": snapshot.get("candidate_a_votes"),
        "candidate_b_votes": snapshot.get("candidate_b_votes"),
        "vote_gap_abs": snapshot.get("vote_gap_abs"),
        "duplicate": duplicate,
        "latest_persisted_sequence": latest_persisted_sequence,
        "result": result,
    }


def _record_capture_debug(debug: dict) -> None:
    global LAST_CAPTURE_DEBUG
    LAST_CAPTURE_DEBUG = debug
    LOGGER.info(
        "capture result=%s source=%s profile=%s cache_bypassed=%s actas_pct=%s "
        "candidate_a_votes=%s candidate_b_votes=%s vote_gap_abs=%s duplicate=%s latest_sequence=%s",
        debug.get("result"),
        debug.get("source"),
        debug.get("http_profile"),
        debug.get("cache_bypassed"),
        debug.get("actas_pct"),
        debug.get("candidate_a_votes"),
        debug.get("candidate_b_votes"),
        debug.get("vote_gap_abs"),
        debug.get("duplicate"),
        debug.get("latest_persisted_sequence"),
    )
    try:
        st.session_state["last_capture_debug"] = debug
    except Exception:
        return


def capture_cycle(force: bool = False) -> CaptureResult:
    if SOURCE_MODE == "REAL_READ_ONLY" and not REAL_ONPE_ENABLED:
        st.warning("REAL_READ_ONLY está configurado, pero el conector real ONPE está desactivado.")
        return "failed"
    try:
        snapshot = select_onpe_snapshot_source(force=force)
    except RuntimeError as exc:
        st.warning(str(exc))
        return "failed"
    except Exception as exc:
        LOGGER.exception("capture failed")
        st.warning(f"No se pudo completar la captura: {exc}")
        return "failed"
    digest = snapshot_hash(snapshot)
    content_digest = snapshot_content_hash(snapshot)
    snapshot.setdefault("snapshot_hash", digest)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshots = read_jsonl(SNAPSHOTS_PATH)
    previous_content_digest = snapshot_content_hash(snapshots[-1]["snapshot"]) if snapshots else None
    latest_sequence = snapshots[-1]["snapshot"].get("sequence", "-") if snapshots else "-"
    if snapshots and previous_content_digest == content_digest:
        _record_capture_debug(
            _capture_debug_payload(
                snapshot,
                force=force,
                result="unchanged",
                duplicate=True,
                latest_persisted_sequence=latest_sequence,
            )
        )
        return "unchanged"

    artifact_type = "aggregate_snapshot"
    previous_digest = snapshots[-1]["hash"] if snapshots else None
    status = integrity_status(artifact_type, digest, previous_digest)
    snapshot_record = {
        "captured_at": captured_at,
        "hash": digest,
        "content_hash": content_digest,
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
    _record_capture_debug(
        _capture_debug_payload(
            snapshot,
            force=force,
            result="captured",
            duplicate=False,
            latest_persisted_sequence=snapshot["sequence"],
        )
    )
    return "captured"


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


def _render_capture_debug(debug: dict) -> None:
    st.caption(
        "Valores extraídos: "
        f"actas={debug.get('actas_pct')}%, "
        f"Keiko={debug.get('candidate_a_votes')}, "
        f"Sánchez={debug.get('candidate_b_votes')}, "
        f"brecha={debug.get('vote_gap_abs')}, "
        f"duplicado={debug.get('duplicate')}, "
        f"última secuencia={debug.get('latest_persisted_sequence')}."
    )


def _official_source_status_text() -> str:
    if SOURCE_MODE == "MOCK":
        return "El sistema opera en modo MOCK. No se están capturando datos reales de ONPE."
    if SOURCE_MODE == "REAL_READ_ONLY":
        return (
            "El sistema opera en modo REAL_READ_ONLY. Solo captura datos públicos oficiales de ONPE, "
            "sin modificar fuentes externas."
        )
    return f"El sistema opera en modo {SOURCE_MODE}."


def auto_capture_is_eligible(source_mode: str, real_onpe_enabled: bool) -> bool:
    return source_mode == "REAL_READ_ONLY" and real_onpe_enabled


def auto_capture_interval_elapsed(now: float, last_capture_ts: float | None, interval_seconds: int) -> bool:
    if last_capture_ts is None:
        return True
    return now - last_capture_ts >= interval_seconds


def auto_capture_countdown_seconds(now: float, last_capture_ts: float | None, interval_seconds: int) -> int:
    if last_capture_ts is None:
        return 0
    return max(0, int(interval_seconds - (now - last_capture_ts)))


def should_auto_capture_rerun(auto_capture_enabled: bool, eligible: bool) -> bool:
    return auto_capture_enabled and eligible


def _format_utc_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _render_auto_capture_controls() -> tuple[bool, int, bool]:
    auto_capture_enabled = st.checkbox("Activar auto-captura ONPE real", value=False)
    interval_seconds = st.selectbox(
        "Intervalo de auto-captura",
        AUTO_CAPTURE_INTERVALS,
        index=0,
        format_func=lambda value: f"{value} segundos",
    )
    st.caption("La auto-captura solo funciona en REAL_READ_ONLY con ONPE real habilitado.")

    last_capture_ts = st.session_state.get("last_auto_capture_ts")
    if last_capture_ts is not None:
        st.caption(f"Última auto-captura: {_format_utc_timestamp(float(last_capture_ts))}")

    if not auto_capture_enabled:
        return False, int(interval_seconds), False

    eligible = auto_capture_is_eligible(SOURCE_MODE, REAL_ONPE_ENABLED)
    if not eligible:
        st.warning("La auto-captura ONPE real requiere SOURCE_MODE=REAL_READ_ONLY y REAL_ONPE_ENABLED=True.")
        return True, int(interval_seconds), False

    countdown = auto_capture_countdown_seconds(time.time(), last_capture_ts, int(interval_seconds))
    if countdown > 0:
        st.caption(f"Próxima auto-captura en {countdown} segundos.")
    return True, int(interval_seconds), True


def _maybe_run_auto_capture_after_render(
    auto_capture_enabled: bool,
    interval_seconds: int,
    eligible: bool,
) -> None:
    _startup_log("before_auto_capture")
    if not should_auto_capture_rerun(auto_capture_enabled, eligible):
        return
    if not st.session_state.get("dashboard_has_rendered"):
        return

    last_capture_ts = st.session_state.get("last_auto_capture_ts")
    now = time.time()
    if auto_capture_interval_elapsed(now, last_capture_ts, interval_seconds):
        result = capture_cycle(force=True)
        st.session_state["last_auto_capture_ts"] = now
        if result == "captured":
            st.sidebar.success("Auto-captura ONPE real ejecutada.")
        elif result == "unchanged":
            st.sidebar.info("Sin cambios nuevos respecto al último snapshot.")


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
    _startup_log("dashboard_start")
    st.title("Personero Digital")
    _render_disclaimers()
    auto_capture_enabled = False
    auto_capture_interval = AUTO_CAPTURE_INTERVALS[0]
    auto_capture_eligible = False
    with st.sidebar:
        st.header("Controles")
        st.caption(f"Fuente de datos: {SOURCE_MODE}")
        st.caption(f"Estado fuente real ONPE: {REAL_SOURCE_STATUS}")
        st.caption(f"Perfil HTTP ONPE: {ONPE_HTTP_PROFILE}")
        st.caption(f"Real ONPE habilitado: {REAL_ONPE_ENABLED}")
        st.caption(REAL_SOURCE_STATUS_NOTE)
        if "capture_success_message" in st.session_state:
            message = st.session_state.pop("capture_success_message")
            if message == "Sin cambios nuevos respecto al último snapshot.":
                st.info(message)
            else:
                st.success(message)
        if st.button(_capture_button_label(), type="primary"):
            result = capture_cycle(force=True)
            if result == "captured":
                st.session_state["capture_success_message"] = _capture_success_message()
            elif result == "unchanged":
                st.session_state["capture_success_message"] = "Sin cambios nuevos respecto al último snapshot."
            st.rerun()
        force_real_enabled = SOURCE_MODE == "REAL_READ_ONLY" and REAL_ONPE_ENABLED
        if st.sidebar.button("Forzar captura ONPE real ahora", disabled=not force_real_enabled):
            result = capture_cycle(force=True)
            if result == "captured":
                st.success("Snapshot ONPE real capturado en modo solo lectura.")
            elif result == "unchanged":
                st.info("Sin cambios nuevos respecto al último snapshot.")
            else:
                st.warning("No se pudo capturar snapshot ONPE real.")
        if st.button("Captura con caché"):
            capture_cycle(force=False)
            st.rerun()
        if "last_capture_debug" in st.session_state:
            _render_capture_debug(st.session_state["last_capture_debug"])
        auto_capture_enabled, auto_capture_interval, auto_capture_eligible = _render_auto_capture_controls()
        if st.button("Generar 12 snapshots mock"):
            generate_mock_snapshots(12)
            st.rerun()
        if st.button("Generar escenario de congelación"):
            generate_freeze_scenario()
            st.rerun()
    _startup_log("controls_rendered")

    snapshots = read_jsonl(SNAPSHOTS_PATH)
    events = read_jsonl(EVENTS_PATH)
    cases = read_jsonl(CASES_PATH)
    _startup_log(f"snapshots_loaded snapshots={len(snapshots)} events={len(events)} cases={len(cases)}")

    tabs = st.tabs(["Resumen", "Comportamiento Electoral", "Feed SOC", "Integridad", "Casos", "Metodología"])
    with tabs[0]:
        _startup_log("render_tab_resumen")
        _render_overview(snapshots, cases, events)
    with tabs[1]:
        _startup_log("render_tab_comportamiento")
        render_electoral_behavior(snapshots, events, cases)
    with tabs[2]:
        _startup_log("render_tab_soc")
        render_soc_feed(events)
    with tabs[3]:
        _startup_log("render_tab_integridad")
        render_integrity_view(snapshots, events)
    with tabs[4]:
        _startup_log("render_tab_casos")
        render_case_view(cases)
    with tabs[5]:
        _startup_log("render_tab_metodologia")
        _render_methodology()
    _startup_log("tabs_rendered")
    _startup_log("dashboard_render_complete")
    _maybe_run_auto_capture_after_render(auto_capture_enabled, auto_capture_interval, auto_capture_eligible)
    st.session_state["dashboard_has_rendered"] = True


if _running_as_streamlit_entrypoint():
    st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="PD")
    render_dashboard()
