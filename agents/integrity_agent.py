from __future__ import annotations

from typing import Any

from config import FREEZE_THRESHOLD_PCT
from storage.json_store import canonical_hash

HASH_ALERT_ARTIFACT_TYPES = {"document", "acta"}


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return canonical_hash(snapshot)


def integrity_status(
    artifact_type: str,
    digest: str,
    previous_digest: str | None,
    same_artifact: bool = False,
) -> str:
    if artifact_type == "aggregate_snapshot":
        return "EXPECTED_CHANGE"
    if previous_digest is None or not same_artifact:
        return "STABLE"
    if artifact_type in HASH_ALERT_ARTIFACT_TYPES and previous_digest != digest:
        return "HASH_CHANGED"
    return "STABLE"


def integrity_events(
    snapshot: dict[str, Any],
    digest: str,
    previous_digest: str | None,
    artifact_type: str = "aggregate_snapshot",
    document_id: str | None = None,
    previous_document_id: str | None = None,
) -> list[dict[str, Any]]:
    same_artifact = bool(document_id and document_id == previous_document_id)
    status = integrity_status(artifact_type, digest, previous_digest, same_artifact)
    events = [
        {
            "type": "SNAPSHOT_CAPTURED",
            "summary": "Public mock snapshot captured and hashed.",
            "severity": "info",
            "snapshot_hash": digest,
            "artifact_type": artifact_type,
            "integrity_status": status,
            "sequence": snapshot["sequence"],
        }
    ]
    if status == "HASH_CHANGED":
        events.append(
            {
                "type": "DOCUMENT_HASH_CHANGED",
                "summary": "Stable document or acta content hash changed across captures.",
                "severity": "low",
                "snapshot_hash": digest,
                "previous_hash": previous_digest,
                "artifact_type": artifact_type,
                "document_id": document_id,
                "integrity_status": status,
                "sequence": snapshot["sequence"],
            }
        )
    if snapshot["actas_contabilizadas_pct"] >= FREEZE_THRESHOLD_PCT:
        events.append(
            {
                "type": "SYSTEM_FROZEN",
                "summary": "Observation window frozen because counted actas reached threshold.",
                "severity": "high",
                "snapshot_hash": digest,
                "artifact_type": artifact_type,
                "integrity_status": status,
                "sequence": snapshot["sequence"],
            }
        )
    return events
