from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib

from src.literature_review.discovery.normalization import (
    normalize_arxiv_id,
    normalize_author,
    normalize_doi,
    normalize_title_key,
)
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ProviderPaper,
    ScreeningRecommendation,
)


@dataclass(frozen=True)
class AmbiguousMatch:
    candidate_id: str
    provider_id: str
    reason: str


def _author_surnames(authors: tuple[str, ...]) -> set[str]:
    return {
        normalize_author(author).replace(",", " ").split()[-1].lower()
        for author in authors
        if normalize_author(author)
    }


def _identity(candidate: CandidatePaper, paper: ProviderPaper) -> bool:
    pairs = (
        (normalize_doi(candidate.doi), normalize_doi(paper.doi)),
        (
            normalize_arxiv_id(candidate.arxiv_id),
            normalize_arxiv_id(paper.arxiv_id),
        ),
        (
            candidate.semantic_scholar_id,
            paper.semantic_scholar_id,
        ),
    )
    if any(left and right and left == right for left, right in pairs):
        return True
    left_title = normalize_title_key(candidate.title)
    right_title = normalize_title_key(paper.title)
    if left_title == right_title and candidate.year == paper.year:
        return True
    return SequenceMatcher(None, left_title, right_title).ratio() >= 0.94 and bool(
        _author_surnames(candidate.authors) & _author_surnames(paper.authors)
    )


def _candidate_id(
    paper: ProviderPaper,
    *,
    disambiguator: str | None = None,
) -> str:
    strongest = (
        normalize_doi(paper.doi)
        or normalize_arxiv_id(paper.arxiv_id)
        or paper.semantic_scholar_id
        or f"{normalize_title_key(paper.title)}:{paper.year}"
    )
    identity = strongest if disambiguator is None else f"{strongest}\0{disambiguator}"
    return "cand_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _new_candidate(
    paper: ProviderPaper,
    *,
    disambiguator: str | None = None,
) -> CandidatePaper:
    return CandidatePaper(
        candidate_id=_candidate_id(paper, disambiguator=disambiguator),
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        abstract=paper.abstract,
        doi=normalize_doi(paper.doi),
        arxiv_id=normalize_arxiv_id(paper.arxiv_id),
        semantic_scholar_id=paper.semantic_scholar_id,
        source_urls=(paper.source_url,),
        open_access_pdf_url=paper.open_access_pdf_url,
        provenance=(f"{paper.provider}:{paper.provider_id}",),
        recommendation=ScreeningRecommendation.REVIEW,
        relevance_score=0.0,
        status=CandidateStatus.PENDING,
    )


def _merge(candidate: CandidatePaper, paper: ProviderPaper) -> CandidatePaper:
    return replace(
        candidate,
        title=candidate.title or paper.title,
        authors=candidate.authors or paper.authors,
        year=candidate.year or paper.year,
        venue=candidate.venue or paper.venue,
        abstract=candidate.abstract or paper.abstract,
        doi=candidate.doi or normalize_doi(paper.doi),
        arxiv_id=candidate.arxiv_id or normalize_arxiv_id(paper.arxiv_id),
        semantic_scholar_id=(
            candidate.semantic_scholar_id or paper.semantic_scholar_id
        ),
        source_urls=tuple(sorted(set(candidate.source_urls) | {paper.source_url})),
        open_access_pdf_url=(
            candidate.open_access_pdf_url or paper.open_access_pdf_url
        ),
        provenance=tuple(
            sorted(
                set(candidate.provenance) | {f"{paper.provider}:{paper.provider_id}"}
            )
        ),
    )


def deduplicate_papers(
    papers: list[ProviderPaper] | tuple[ProviderPaper, ...],
) -> tuple[list[CandidatePaper], list[AmbiguousMatch]]:
    candidates: list[CandidatePaper] = []
    ambiguous: list[AmbiguousMatch] = []
    for paper in papers:
        match = next(
            (candidate for candidate in candidates if _identity(candidate, paper)),
            None,
        )
        if match is None:
            candidates.append(_new_candidate(paper))
            continue
        author_overlap = bool(
            _author_surnames(match.authors) & _author_surnames(paper.authors)
        )
        if (
            match.year is not None
            and paper.year is not None
            and match.year != paper.year
        ) or not author_overlap:
            ambiguous.append(
                AmbiguousMatch(
                    match.candidate_id,
                    paper.provider_id,
                    "conflicting year or disjoint authors",
                )
            )
            candidates.append(
                _new_candidate(
                    paper,
                    disambiguator=f"{paper.provider}:{paper.provider_id}",
                )
            )
            continue
        candidates[candidates.index(match)] = _merge(match, paper)
    return candidates, ambiguous


__all__ = ["AmbiguousMatch", "deduplicate_papers"]
