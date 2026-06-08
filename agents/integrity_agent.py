from __future__ import annotations

from typing import Any

from config import FREEZE_THRESHOLD_PCT
from storage.json_store import canonical_hash

HASH_ALERT_ARTIFACT_TYPES = {"document", "acta"}
SNAPSHOT_CONTENT_HASH_FIELDS = (
    "source",
    "source_mode",
    "collection_mode",
    "election_id",
    "candidate_a_name",
    "candidate_b_name",
    "candidate_a_votes",
    "candidate_b_votes",
    "candidate_a_pct",
    "candidate_b_pct",
    "vote_gap_abs",
    "vote_gap_pct",
    "actas_contabilizadas_pct",
    "actas_contabilizadas",
    "total_actas",
    "total_votos_validos",
    "total_votos_emitidos",
    "fecha_actualizacion_onpe",
)


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return canonical_hash(snapshot)


def snapshot_content_hash(snapshot: dict[str, Any]) -> str:
    """Hash stable extracted result fields for duplicate capture detection."""
    content = {field: snapshot.get(field) for field in SNAPSHOT_CONTENT_HASH_FIELDS if field in snapshot}
    return canonical_hash(content)


def snapshot_captured_summary(snapshot: dict[str, Any]) -> str:
    source_mode = snapshot.get("source_mode")
    source = snapshot.get("source")
    if source_mode == "MOCK" or source == "MOCK_ONPE_PUBLIC_DATA":
        return "Snapshot mock capturado y hasheado."
    if source_mode == "REAL_READ_ONLY" or source == "ONPE_REAL_PUBLIC_DATA":
        return "Snapshot público ONPE en modo solo lectura capturado y hasheado."
    return "Snapshot público capturado y hasheado."


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
            "summary": snapshot_captured_summary(snapshot),
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
