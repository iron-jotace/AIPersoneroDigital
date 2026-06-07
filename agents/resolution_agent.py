from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def close_case(case: dict[str, Any], reason: str = "Manual review completed") -> dict[str, Any]:
    updated = dict(case)
    lifecycle = list(updated.get("lifecycle", []))
    if "CLOSED" not in lifecycle:
        lifecycle.append("CLOSED")
    updated["status"] = "CLOSED"
    updated["closed_at"] = datetime.now(timezone.utc).isoformat()
    updated["resolution_note"] = reason
    updated["lifecycle"] = lifecycle
    return updated

