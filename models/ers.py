from __future__ import annotations


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_ers(
    stat_norm: float,
    integrity_norm: float,
    persistence_norm: float,
    multi_source_norm: float,
    context_norm: float,
) -> float:
    score = (
        0.30 * _clamp(stat_norm)
        + 0.25 * _clamp(integrity_norm)
        + 0.20 * _clamp(persistence_norm)
        + 0.15 * _clamp(multi_source_norm)
        + 0.10 * _clamp(context_norm)
    )
    return round(score, 3)

