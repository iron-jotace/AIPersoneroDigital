from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.confidence import confidence_score, evidence_level


CASE_STATUSES = {
    "DETECTED",
    "CASE_OPENED",
    "UNDER_REVIEW",
    "EXPLAINED",
    "DISMISSED",
    "ESCALATED",
    "CLOSED",
}


def build_case(event: dict[str, Any]) -> dict[str, Any]:
    confidence = confidence_score(
        source_official=True,
        hash_snapshot=True,
        reproducibility=True,
        human_review=False,
        multi_artifact_consistency=False,
    )
    return {
        "case_id": f"PD-{event['sequence']:04d}-{event['snapshot_hash'][:8]}",
        "status": "CASE_OPENED",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "event_type": event["type"],
        "summary": event["summary"],
        "detector_explanation": (
            "The MAD detector observed unusual movement in the Keiko-Sánchez vote gap. "
            "Comportamiento observado desde snapshots capturados. "
            "Un movimiento de brecha no constituye evidencia de fraude. "
            "Una anomalía estadística solo indica movimiento inusual que requiere revisión."
        ),
        "non_conclusive_note": "Caso abierto para revisión humana; no constituye prueba de fraude.",
        "snapshot_hash": event["snapshot_hash"],
        "sequence": event["sequence"],
        "metrics": {
            "metric": event.get("metric"),
            "value": event.get("value"),
            "mad_z": event.get("mad_z"),
            "ers": event.get("ers", 0),
        },
        "confidence_score": confidence,
        "evidence_level": evidence_level(confidence),
        "lifecycle": ["DETECTED", "CASE_OPENED"],
        "artifacts": [
            {"kind": "snapshot_hash", "value": event["snapshot_hash"]},
            {"kind": "detector", "value": "MAD vote-gap evolution"},
        ],
    }


def case_events(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "CASE_OPENED",
            "summary": f"Evidence case {case['case_id']} opened for human review.",
            "severity": "medium",
            "snapshot_hash": case["snapshot_hash"],
            "sequence": case["sequence"],
            "case_id": case["case_id"],
        }
    ]


def review_action_event(
    case: dict[str, Any],
    previous_status: str,
    new_status: str,
    justification: str,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "type": "REVIEW_ACTION",
        "event_model": "ReviewAction",
        "summary": f"Manual review action changed {case['case_id']} from {previous_status} to {new_status}.",
        "severity": "info",
        "reviewer": "local_operator",
        "timestamp": timestamp,
        "captured_at": timestamp,
        "previous_status": previous_status,
        "new_status": new_status,
        "justification": justification,
        "snapshot_hash": case["snapshot_hash"],
        "sequence": case["sequence"],
        "case_id": case["case_id"],
    }


def lifecycle_event(case: dict[str, Any], new_status: str) -> dict[str, Any] | None:
    if new_status == "EXPLAINED":
        return {
            "type": "CASE_EXPLAINED",
            "summary": f"Evidence case {case['case_id']} marked explained by human review.",
            "severity": "info",
            "snapshot_hash": case["snapshot_hash"],
            "sequence": case["sequence"],
            "case_id": case["case_id"],
        }
    if new_status == "CLOSED":
        return {
            "type": "CASE_CLOSED",
            "summary": f"Evidence case {case['case_id']} closed by human review.",
            "severity": "info",
            "snapshot_hash": case["snapshot_hash"],
            "sequence": case["sequence"],
            "case_id": case["case_id"],
        }
    return None


def apply_review_action(case: dict[str, Any], new_status: str, justification: str) -> dict[str, Any]:
    if new_status not in CASE_STATUSES:
        raise ValueError(f"Unsupported case status: {new_status}")
    updated = dict(case)
    previous_status = str(updated.get("status", "CASE_OPENED"))
    lifecycle = list(updated.get("lifecycle", []))
    if new_status not in lifecycle:
        lifecycle.append(new_status)
    action = review_action_event(updated, previous_status, new_status, justification)
    review_actions = list(updated.get("review_actions", []))
    review_actions.append(action)
    updated["status"] = new_status
    updated["lifecycle"] = lifecycle
    updated["review_actions"] = review_actions
    updated["updated_at"] = action["timestamp"]
    if new_status == "CLOSED":
        updated["closed_at"] = action["timestamp"]
    return updated
