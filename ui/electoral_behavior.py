from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config import CANDIDATE_A_NAME, CANDIDATE_B_NAME


def _snapshot_frame(snapshots: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for item in snapshots:
        snapshot = item["snapshot"]
        rows.append(
            {
                "snapshot": snapshot["sequence"],
                "captured_at": snapshot["captured_at"],
                f"{CANDIDATE_A_NAME} pct": snapshot.get("candidate_a_pct", 0.0),
                f"{CANDIDATE_B_NAME} pct": snapshot.get("candidate_b_pct", 0.0),
                f"{CANDIDATE_A_NAME} votes": snapshot.get("candidate_a_votes", 0),
                f"{CANDIDATE_B_NAME} votes": snapshot.get("candidate_b_votes", 0),
                "Keiko - Sánchez vote gap": snapshot.get("vote_gap_abs", 0),
                "Keiko - Sánchez gap pct": snapshot.get("vote_gap_pct", 0.0),
                "Last snapshot pct": snapshot.get("actas_contabilizadas_pct", 0.0),
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
                "snapshot": event.get("sequence"),
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
    marker_value_column: str | None = None,
) -> None:
    base = alt.Chart(frame).encode(x=alt.X("snapshot:Q", title="Snapshot"))
    line = base.mark_line(point=True).encode(y=alt.Y(f"{y_column}:Q", title=y_column))

    if anomalies.empty:
        st.altair_chart(line, use_container_width=True)
        return

    marker_column = marker_value_column or y_column
    marker_frame = anomalies.merge(frame[["snapshot", marker_column]], on="snapshot", how="left")
    markers = (
        alt.Chart(marker_frame)
        .mark_point(size=110, filled=True, color="#c43c39")
        .encode(
            x=alt.X("snapshot:Q", title="Snapshot"),
            y=alt.Y(f"{marker_column}:Q", title=y_column),
            tooltip=[
                alt.Tooltip("snapshot:Q", title="Snapshot"),
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

    frame = _snapshot_frame(snapshots)
    latest = frame.iloc[-1]
    kpis = st.columns(6)
    kpis[0].metric("Votos Keiko Fujimori", f"{int(latest[f'{CANDIDATE_A_NAME} votes']):,}")
    kpis[1].metric("Votos Roberto Sánchez", f"{int(latest[f'{CANDIDATE_B_NAME} votes']):,}")
    kpis[2].metric("Keiko - Sánchez vote gap", f"{int(latest['Keiko - Sánchez vote gap']):,}")
    kpis[3].metric("Keiko - Sánchez gap pct", f"{latest['Keiko - Sánchez gap pct']}%")
    kpis[4].metric("Último % de actas", f"{latest['Last snapshot pct']}%")
    kpis[5].metric("Última secuencia", int(latest["snapshot"]))

    anomalies = _anomaly_frame(events, cases)

    st.markdown("**Evolución porcentual del voto**")
    pct_frame = frame.melt(
        id_vars=["snapshot"],
        value_vars=[f"{CANDIDATE_A_NAME} pct", f"{CANDIDATE_B_NAME} pct"],
        var_name="candidate",
        value_name="pct",
    )
    pct_chart = (
        alt.Chart(pct_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("snapshot:Q", title="Snapshot"),
            y=alt.Y("pct:Q", title="Vote percentage", scale=alt.Scale(domain=[45, 55])),
            color=alt.Color("candidate:N", title="Candidate"),
            tooltip=[
                alt.Tooltip("snapshot:Q", title="Snapshot"),
                alt.Tooltip("candidate:N", title="Candidate"),
                alt.Tooltip("pct:Q", title="Percent"),
            ],
        )
    )
    reference_50 = alt.Chart(pd.DataFrame({"pct": [50]})).mark_rule(
        color="#666666",
        strokeDash=[4, 4],
    ).encode(y="pct:Q")
    st.altair_chart(pct_chart + reference_50, use_container_width=True)

    st.caption(
        "● Punto rojo = movimiento inusual detectado por MAD; requiere revisión humana. "
        "No constituye evidencia de fraude."
    )

    st.markdown("**Evolución absoluta de la brecha Keiko - Sánchez**")
    _line_with_markers(frame, anomalies, "Keiko - Sánchez vote gap")

    st.markdown("**Evolución porcentual de la brecha Keiko - Sánchez**")
    _line_with_markers(frame, anomalies, "Keiko - Sánchez gap pct")

    st.markdown("**Avance de snapshots**")
    progression_chart = (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("snapshot:Q", title="Snapshot"),
            y=alt.Y("Last snapshot pct:Q", title="Último % de actas"),
            tooltip=[
                alt.Tooltip("snapshot:Q", title="Snapshot"),
                alt.Tooltip("captured_at:N", title="Captured at"),
                alt.Tooltip("Last snapshot pct:Q", title="Último % de actas"),
            ],
        )
    )
    st.altair_chart(progression_chart, use_container_width=True)

    table_frame = (
        frame.assign(
            snapshot_hash=[item.get("snapshot_hash", item.get("hash", "")) for item in snapshots],
            actas_contabilizadas_pct=frame["Last snapshot pct"],
        )
        .rename(
            columns={
                "snapshot": "sequence",
                f"{CANDIDATE_A_NAME} votes": "Votos Keiko Fujimori",
                f"{CANDIDATE_B_NAME} votes": "Votos Roberto Sánchez",
                "Keiko - Sánchez vote gap": "Keiko - Sánchez gap",
                "Keiko - Sánchez gap pct": "Keiko - Sánchez gap pct",
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
