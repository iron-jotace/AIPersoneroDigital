from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config import CANDIDATE_A_NAME, CANDIDATE_B_NAME


def _snapshot_payload(item: dict) -> dict:
    return item.get("snapshot", item)


def filter_real_behavior_snapshots(snapshot_records: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for item in snapshot_records:
        snapshot = _snapshot_payload(item)
        source_mode = str(snapshot.get("source_mode", "")).upper()
        source = str(snapshot.get("source", "")).upper()
        collection_mode = str(snapshot.get("collection_mode", "")).lower()

        if source_mode == "MOCK":
            continue
        if "MOCK" in source:
            continue
        if any(token in collection_mode for token in ("mock", "demo", "freeze", "frozen", "system_frozen")):
            continue
        if source_mode != "REAL_READ_ONLY":
            continue

        filtered.append(snapshot)
    return filtered


def build_vote_pct_long_df(snapshots: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for snapshot in snapshots:
        sequence = snapshot["sequence"]
        rows.extend(
            [
                {
                    "sequence": sequence,
                    "candidate": snapshot.get("candidate_a_name", CANDIDATE_A_NAME),
                    "vote_pct": snapshot.get("candidate_a_pct", 0.0),
                },
                {
                    "sequence": sequence,
                    "candidate": snapshot.get("candidate_b_name", CANDIDATE_B_NAME),
                    "vote_pct": snapshot.get("candidate_b_pct", 0.0),
                },
            ]
        )
    return pd.DataFrame(rows, columns=["sequence", "candidate", "vote_pct"])


def build_gap_evolution_df(snapshots: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for snapshot in snapshots:
        rows.append(
            {
                "sequence": snapshot["sequence"],
                "captured_at": snapshot["captured_at"],
                "actas_contabilizadas_pct": snapshot.get("actas_contabilizadas_pct", 0.0),
                "candidate_a_name": snapshot.get("candidate_a_name", CANDIDATE_A_NAME),
                "candidate_a_pct": snapshot.get("candidate_a_pct", 0.0),
                "candidate_a_votes": snapshot.get("candidate_a_votes", 0),
                "candidate_b_name": snapshot.get("candidate_b_name", CANDIDATE_B_NAME),
                "candidate_b_pct": snapshot.get("candidate_b_pct", 0.0),
                "candidate_b_votes": snapshot.get("candidate_b_votes", 0),
                "vote_gap_abs": snapshot.get("vote_gap_abs", 0),
                "vote_gap_pct": snapshot.get("vote_gap_pct", 0.0),
                "source_mode": snapshot.get("source_mode", ""),
                "collection_mode": snapshot.get("collection_mode", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
            }
        )
    return pd.DataFrame(rows)


def _anomaly_frame(events: list[dict], cases: list[dict]) -> pd.DataFrame:
    case_by_sequence = {case["sequence"]: case for case in cases}
    rows: list[dict] = []
    for event in events:
        if event.get("type") != "ANOMALY_DETECTED":
            continue
        case = case_by_sequence.get(event.get("sequence"), {})
        rows.append(
            {
                "sequence": event.get("sequence"),
                "MAD score": event.get("mad_z"),
                "ERS": event.get("ers"),
                "evidence_level": case.get("evidence_level", ""),
                "case_id": case.get("case_id", ""),
                "summary": event.get("summary", ""),
            }
        )
    return pd.DataFrame(rows)


def _line_with_markers(
    frame: pd.DataFrame,
    anomalies: pd.DataFrame,
    y_column: str,
) -> None:
    base = alt.Chart(frame).encode(x=alt.X("sequence:Q", title="Snapshot"))
    line = base.mark_line(point=True).encode(y=alt.Y(f"{y_column}:Q", title=y_column))

    if anomalies.empty:
        st.altair_chart(line, use_container_width=True)
        return

    marker_frame = anomalies.merge(frame[["sequence", y_column]], on="sequence", how="inner")
    if marker_frame.empty:
        st.altair_chart(line, use_container_width=True)
        return
    markers = (
        alt.Chart(marker_frame)
        .mark_point(size=110, filled=True, color="#c43c39")
        .encode(
            x=alt.X("sequence:Q", title="Snapshot"),
            y=alt.Y(f"{y_column}:Q", title=y_column),
            tooltip=[
                alt.Tooltip("sequence:Q", title="Snapshot"),
                alt.Tooltip("MAD score:Q", title="MAD score"),
                alt.Tooltip("ERS:Q", title="ERS"),
                alt.Tooltip("evidence_level:N", title="Evidence level"),
                alt.Tooltip("case_id:N", title="Case ID"),
                alt.Tooltip("summary:N", title="Observed note"),
            ],
        )
    )
    st.altair_chart(line + markers, use_container_width=True)


def render_electoral_behavior(snapshots: list[dict], events: list[dict], cases: list[dict]) -> None:
    st.subheader("Comportamiento Electoral")
    with st.container(border=True):
        st.markdown("**Comportamiento observado, no proyección**")
        st.write(
            "Esta vista muestra únicamente el comportamiento observado en snapshots capturados. "
            "No proyecta el resultado final, no estima votos pendientes y no asigna probabilidad de victoria."
        )
    st.caption(
        "Un movimiento inusual requiere revisión humana y se interpreta únicamente desde snapshots capturados."
    )

    if not snapshots:
        st.info("No snapshots captured yet.")
        return

    behavior_snapshots = filter_real_behavior_snapshots(snapshots)
    if not behavior_snapshots:
        st.warning("No hay registros válidos de snapshots reales disponibles para las gráficas de comportamiento.")
        return

    frame = build_gap_evolution_df(behavior_snapshots)
    pct_frame = build_vote_pct_long_df(behavior_snapshots)
    latest = frame.iloc[-1]
    kpis = st.columns(6)
    kpis[0].metric("Votos Keiko Fujimori", f"{int(latest['candidate_a_votes']):,}")
    kpis[1].metric("Votos Roberto Sánchez", f"{int(latest['candidate_b_votes']):,}")
    kpis[2].metric("Keiko - Sánchez vote gap", f"{int(latest['vote_gap_abs']):,}")
    kpis[3].metric("Keiko - Sánchez gap pct", f"{latest['vote_gap_pct']}%")
    kpis[4].metric("Último % de actas", f"{latest['actas_contabilizadas_pct']}%")
    kpis[5].metric("Última secuencia", int(latest["sequence"]))

    anomalies = _anomaly_frame(events, cases)

    st.markdown("**Evolución porcentual del voto**")
    pct_chart = (
        alt.Chart(pct_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("sequence:Q", title="Snapshot"),
            y=alt.Y("vote_pct:Q", title="Vote percentage", scale=alt.Scale(domain=[45, 55])),
            color=alt.Color("candidate:N", title="Candidate"),
            tooltip=[
                alt.Tooltip("sequence:Q", title="Snapshot"),
                alt.Tooltip("candidate:N", title="Candidate"),
                alt.Tooltip("vote_pct:Q", title="Percent"),
            ],
        )
    )
    reference_50 = alt.Chart(pd.DataFrame({"vote_pct": [50]})).mark_rule(
        color="#666666",
        strokeDash=[4, 4],
    ).encode(y="vote_pct:Q")
    st.altair_chart(pct_chart + reference_50, use_container_width=True)

    st.caption(
        "● Punto rojo = movimiento inusual detectado por MAD; requiere revisión humana. "
        "No constituye evidencia de fraude."
    )

    st.markdown("**Evolución absoluta de la brecha Keiko - Sánchez**")
    _line_with_markers(frame, anomalies, "vote_gap_abs")

    st.markdown("**Evolución porcentual de la brecha Keiko - Sánchez**")
    _line_with_markers(frame, anomalies, "vote_gap_pct")

    st.markdown("**Avance de snapshots**")
    progression_chart = (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("sequence:Q", title="Snapshot"),
            y=alt.Y("actas_contabilizadas_pct:Q", title="Último % de actas"),
            tooltip=[
                alt.Tooltip("sequence:Q", title="Snapshot"),
                alt.Tooltip("captured_at:N", title="Captured at"),
                alt.Tooltip("actas_contabilizadas_pct:Q", title="Último % de actas"),
            ],
        )
    )
    st.altair_chart(progression_chart, use_container_width=True)

    table_frame = (
        frame.copy()
        .rename(
            columns={
                "candidate_a_votes": "Votos Keiko Fujimori",
                "candidate_b_votes": "Votos Roberto Sánchez",
                "vote_gap_abs": "Keiko - Sánchez gap",
                "vote_gap_pct": "Keiko - Sánchez gap pct",
            }
        )
        [
            [
                "sequence",
                "captured_at",
                "actas_contabilizadas_pct",
                "Votos Keiko Fujimori",
                "Votos Roberto Sánchez",
                "Keiko - Sánchez gap",
                "Keiko - Sánchez gap pct",
                "snapshot_hash",
            ]
        ]
        .sort_values("sequence", ascending=False)
        .head(15)
    )
    st.markdown("**Snapshots observados**")
    st.dataframe(table_frame, width="stretch", hide_index=True)
