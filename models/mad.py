from __future__ import annotations

from statistics import median


def mad_z_scores(values: list[float]) -> list[float]:
    """Return modified z-scores based on the median absolute deviation.

    The implementation uses 0.6745 as the normal consistency factor for MAD.
    Multiplying by 0.6745 is equivalent to dividing by 1.4826 * MAD. These
    scores are used for relative anomaly detection, not proof of irregularity.
    """
    if not values:
        return []
    med = median(values)
    deviations = [abs(value - med) for value in values]
    mad = median(deviations)
    if mad == 0:
        return [0.0 if value == med else 8.0 for value in values]
    return [abs(0.6745 * (value - med) / mad) for value in values]
