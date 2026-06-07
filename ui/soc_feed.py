from __future__ import annotations

import pandas as pd
import streamlit as st


def render_soc_feed(events: list[dict]) -> None:
    st.subheader("Feed SOC")
    if not events:
        st.info("No events captured yet.")
        return
    frame = pd.DataFrame(events)
    columns = [col for col in ["captured_at", "type", "severity", "summary", "sequence", "case_id"] if col in frame]
    st.dataframe(frame[columns].tail(25).iloc[::-1], width="stretch", hide_index=True)
