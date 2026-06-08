from __future__ import annotations

from typing import Any

EXCLUDED_COLLECTION_MARKERS = ("mock", "demo", "freeze", "frozen", "system_frozen")


def snapshot_payload(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("snapshot", item)


def is_real_read_only_snapshot(snapshot: dict[str, Any]) -> bool:
    payload = snapshot_payload(snapshot)
    source_mode = str(payload.get("source_mode", "")).upper()
    source = str(payload.get("source", "")).upper()
    collection_mode = str(payload.get("collection_mode", "")).lower()
    election_id = str(payload.get("election_id", "")).upper()

    if source_mode != "REAL_READ_ONLY":
        return False
    if "MOCK" in source or "MOCK" in election_id:
        return False
    if any(marker in collection_mode for marker in EXCLUDED_COLLECTION_MARKERS):
        return False
    return True


def filter_real_read_only_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [snapshot for snapshot in snapshots if is_real_read_only_snapshot(snapshot)]
