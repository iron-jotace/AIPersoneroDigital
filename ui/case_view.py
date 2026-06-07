from __future__ import annotations

import pandas as pd
import streamlit as st

from agents.evidence_agent import apply_review_action, lifecycle_event
from config import CASES_PATH, EVENTS_PATH
from storage.json_store import append_jsonl, write_jsonl


REVIEW_TRANSITIONS = [
    ("Mark UNDER_REVIEW", "UNDER_REVIEW"),
    ("Mark EXPLAINED", "EXPLAINED"),
    ("Mark DISMISSED", "DISMISSED"),
    ("Mark ESCALATED", "ESCALATED"),
    ("Mark CLOSED", "CLOSED"),
]


def _persist_review_action(cases: list[dict], case_id: str, new_status: str, justification: str) -> None:
    updated_cases: list[dict] = []
    review_event: dict | None = None
    extra_event: dict | None = None
    for case in cases:
        if case["case_id"] != case_id:
            updated_cases.append(case)
            continue
        updated_case = apply_review_action(case, new_status, justification)
        review_event = updated_case["review_actions"][-1]
        extra_event = lifecycle_event(updated_case, new_status)
        updated_cases.append(updated_case)

    write_jsonl(CASES_PATH, updated_cases)
    if review_event:
        append_jsonl(EVENTS_PATH, review_event)
    if extra_event:
        append_jsonl(EVENTS_PATH, extra_event)


def render_case_view(cases: list[dict]) -> None:
    st.subheader("Evidence Case Viewer")
    if not cases:
        st.info("No evidence cases opened.")
        return
    summary = pd.DataFrame(
        [
            {
                "case_id": case["case_id"],
                "status": case["status"],
                "evidence_level": case["evidence_level"],
                "confidence": case["confidence_score"],
                "ers": case["metrics"].get("ers"),
                "summary": case["summary"],
            }
            for case in cases
        ]
    )
    st.dataframe(summary.iloc[::-1], width="stretch", hide_index=True)
    selected = st.selectbox("Case detail", [case["case_id"] for case in cases])
    case = next(item for item in cases if item["case_id"] == selected)
    justification = st.text_input(
        "Review justification",
        value="Manual local review action.",
        key=f"justification_{selected}",
    )
    columns = st.columns(len(REVIEW_TRANSITIONS))
    for column, (label, status) in zip(columns, REVIEW_TRANSITIONS):
        disabled = case.get("status") == status or not justification.strip()
        if column.button(label, key=f"{selected}_{status}", disabled=disabled):
            _persist_review_action(cases, selected, status, justification.strip())
            st.rerun()
    st.json(case)
