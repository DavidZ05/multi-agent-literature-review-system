from __future__ import annotations

from dataclasses import dataclass
import math
import re

from src.literature_review.documents import EvidenceChunk


_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "with", "we", "their", "its", "can", "may", "agent", "agents",
}


@dataclass(frozen=True)
class RetrievalHit:
    chunk: EvidenceChunk
    score: float
    claim_coverage: float
    matched_terms: tuple[str, ...]


class CitationScopedRetriever:
    def __init__(self, *, top_k: int = 5) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.top_k = top_k

    def retrieve(
        self,
        claim_text: str,
        citation_key: str,
        chunks: tuple[EvidenceChunk, ...] | list[EvidenceChunk],
    ) -> tuple[RetrievalHit, ...]:
        scoped = [chunk for chunk in chunks if chunk.citation_key == citation_key]
        claim_terms = set(_terms(claim_text))
        if not scoped or not claim_terms:
            return ()
        frequencies = {
            term: sum(term in set(_terms(chunk.text)) for chunk in scoped)
            for term in claim_terms
        }
        hits: list[RetrievalHit] = []
        for chunk in scoped:
            chunk_terms = set(_terms(chunk.text))
            matched = claim_terms & chunk_terms
            if not matched:
                continue
            coverage = len(matched) / len(claim_terms)
            idf_score = sum(
                math.log((len(scoped) + 1) / (frequencies[term] + 0.5)) + 1
                for term in matched
            ) / max(1, len(claim_terms))
            phrase_bonus = _phrase_bonus(claim_text, chunk.text)
            section_bonus = 0.05 if chunk.section and any(
                term in set(_terms(chunk.section)) for term in claim_terms
            ) else 0.0
            score = round(0.65 * coverage + 0.25 * min(1.0, idf_score) + phrase_bonus + section_bonus, 6)
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=score,
                    claim_coverage=round(coverage, 6),
                    matched_terms=tuple(sorted(matched)),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.page_start, hit.chunk.chunk_id))
        return tuple(hits[: self.top_k])


def _terms(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN.finditer(text))
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _phrase_bonus(claim: str, evidence: str) -> float:
    claim_terms = _terms(claim)
    evidence_text = " ".join(_terms(evidence))
    for size, bonus in ((6, 0.15), (4, 0.10), (3, 0.05)):
        for index in range(max(0, len(claim_terms) - size + 1)):
            if " ".join(claim_terms[index : index + size]) in evidence_text:
                return bonus
    return 0.0


__all__ = ["CitationScopedRetriever", "RetrievalHit"]
