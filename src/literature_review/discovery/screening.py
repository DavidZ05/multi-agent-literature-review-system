from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from src.literature_review.discovery.normalization import normalize_title_key
from src.literature_review.models import (
    CandidatePaper,
    ScreeningRecommendation,
)


@dataclass(frozen=True)
class ScreeningResult:
    recommendation: ScreeningRecommendation
    score: float
    components: Mapping[str, float]
    reasons: tuple[str, ...]
    version: str = "screening-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))


def _overlap(left: str, right: str) -> float:
    right_tokens = set(normalize_title_key(right).split())
    if not right_tokens:
        return 0.0
    left_tokens = set(normalize_title_key(left).split())
    return len(left_tokens & right_tokens) / len(right_tokens)


def screen_candidate(
    candidate: CandidatePaper,
    *,
    topic: str,
    coverage_gap_terms: tuple[str, ...],
    seed_title_keys: tuple[str, ...],
) -> ScreeningResult:
    title_overlap = _overlap(candidate.title, topic)
    abstract_overlap = _overlap(candidate.abstract or "", topic)
    gap_overlap = _overlap(
        f"{candidate.title} {candidate.abstract or ''}",
        " ".join(coverage_gap_terms),
    )
    metadata = 1.0 if candidate.year and candidate.authors else 0.0
    open_access = 1.0 if candidate.open_access_pdf_url else 0.0
    duplicate_penalty = (
        1.0 if normalize_title_key(candidate.title) in set(seed_title_keys) else 0.0
    )
    components = {
        "topic_overlap": 0.45 * title_overlap,
        "abstract_overlap": 0.20 * abstract_overlap,
        "coverage_gap": 0.20 * gap_overlap,
        "stable_metadata": 0.10 * metadata,
        "open_access": 0.05 * open_access,
        "seed_duplicate_penalty": -0.50 * duplicate_penalty,
    }
    score = min(1.0, max(0.0, sum(components.values())))
    if score >= 0.65:
        recommendation = ScreeningRecommendation.INCLUDE
    elif score >= 0.35:
        recommendation = ScreeningRecommendation.REVIEW
    else:
        recommendation = ScreeningRecommendation.EXCLUDE
    reasons = (
        f"title/topic overlap={title_overlap:.2f}",
        f"coverage-gap overlap={gap_overlap:.2f}",
        f"stable metadata={'yes' if metadata else 'no'}",
    )
    return ScreeningResult(recommendation, score, components, reasons)


__all__ = ["ScreeningResult", "screen_candidate"]
