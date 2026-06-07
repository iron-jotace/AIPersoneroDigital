from __future__ import annotations

import pandas as pd
import streamlit as st


def _row_status(item: dict) -> str:
    if "integrity_status" in item:
        return item["integrity_status"]
    if item.get("artifact_type", "aggregate_snapshot") == "aggregate_snapshot":
        return "EXPECTED_CHANGE"
    return "STABLE"


def render_integrity_view(snapshots: list[dict], events: list[dict]) -> None:
    st.subheader("Integrity Monitor")
    if not snapshots:
        st.info("No snapshots persisted.")
        return
    integrity_rows = [
        {
            "sequence": item["snapshot"]["sequence"],
            "captured_at": item["captured_at"],
            "snapshot_hash": item.get("snapshot_hash", item["hash"]),
            "artifact_type": item.get("artifact_type", "aggregate_snapshot"),
            "integrity_status": _row_status(item),
            "actas_pct": item["snapshot"]["actas_contabilizadas_pct"],
        }
        for item in snapshots
    ]
    st.dataframe(pd.DataFrame(integrity_rows).tail(15).iloc[::-1], width="stretch", hide_index=True)
    freeze_events = [event for event in events if event["type"] == "SYSTEM_FROZEN"]
    if freeze_events:
        st.warning("System freeze active: counted actas reached the configured observation threshold.")
