from __future__ import annotations


def confidence_score(
    source_official: bool,
    hash_snapshot: bool,
    reproducibility: bool,
    human_review: bool,
    multi_artifact_consistency: bool,
) -> float:
    weights = {
        "source_official": 0.25,
        "hash_snapshot": 0.25,
        "reproducibility": 0.20,
        "human_review": 0.15,
        "multi_artifact_consistency": 0.15,
    }
    score = (
        weights["source_official"] * float(source_official)
        + weights["hash_snapshot"] * float(hash_snapshot)
        + weights["reproducibility"] * float(reproducibility)
        + weights["human_review"] * float(human_review)
        + weights["multi_artifact_consistency"] * float(multi_artifact_consistency)
    )
    return round(score, 3)


def evidence_level(confidence: float) -> str:
    if confidence >= 0.95:
        return "E5"
    if confidence >= 0.80:
        return "E4"
    if confidence >= 0.65:
        return "E3"
    if confidence >= 0.45:
        return "E2"
    if confidence > 0:
        return "E1"
    return "E0"

