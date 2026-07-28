from __future__ import annotations

import re

from src.literature_review.citations import CITATION_PATTERN
from src.literature_review.verification.models import AtomicClaim, ClaimType


_CITATION = CITATION_PATTERN
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`*])")
_FACTUAL_CUES = re.compile(
    r"\b(?:is|are|was|were|has|have|shows?|reports?|introduces?|"
    r"proposes?|proposed|evaluates?|evaluated|improves?|improved|"
    r"reduces?|reduced|increases?|increased|decreases?|decreased|"
    r"demonstrates?|demonstrated|finds?|found|uses?|used|stores?|stored|"
    r"retrieves?|retrieved)\b",
    re.IGNORECASE,
)
_OPINION_CUES = re.compile(
    r"\b(?:we argue|we recommend|should|could|may be|in our view|future work)\b",
    re.IGNORECASE,
)
_TRANSITION_CUES = re.compile(
    r"^(?:however|therefore|moreover|in contrast|first|second|finally|in summary)\b",
    re.IGNORECASE,
)
_SCOPE_CUES = re.compile(
    r"\b(?:this (?:survey|review|section|project)|research question|"
    r"out of scope|does not claim|we (?:include|exclude|focus|limit))\b",
    re.IGNORECASE,
)


class ClaimExtractor:
    def extract(
        self,
        run_id: str,
        markdown: str,
        *,
        draft_version: int,
    ) -> tuple[AtomicClaim, ...]:
        section = "Preamble"
        paragraph_index = 0
        in_code = False
        claims: list[AtomicClaim] = []
        paragraphs: list[tuple[str, str]] = []
        buffer: list[str] = []

        def flush() -> None:
            nonlocal paragraph_index
            if not buffer or section.lower() == "references":
                buffer.clear()
                return
            paragraph = " ".join(part.strip() for part in buffer if part.strip())
            buffer.clear()
            if paragraph:
                paragraphs.append((section, paragraph))
                paragraph_index += 1

        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                flush()
                in_code = not in_code
                continue
            if in_code:
                continue
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading:
                flush()
                section = heading.group(1).strip()
                continue
            if not line:
                flush()
                continue
            if line.startswith("|") and line.endswith("|"):
                flush()
                if re.fullmatch(r"\|?[\s|:-]+\|?", line):
                    continue
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                row = " ".join(cell for cell in cells if cell)
                if row:
                    paragraphs.append((section, row))
                    paragraph_index += 1
                continue
            if line.startswith(("- ", "* ")):
                flush()
                paragraphs.append((section, line[2:].strip()))
                paragraph_index += 1
                continue
            buffer.append(line)
        flush()

        for paragraph_number, (paragraph_section, paragraph) in enumerate(paragraphs):
            for sentence_number, sentence in enumerate(_split_sentences(paragraph)):
                for clause_number, clause in enumerate(_split_atomic_clauses(sentence)):
                    text = clause.strip()
                    if not text or _is_reference_entry(text):
                        continue
                    citation_keys = tuple(dict.fromkeys(_CITATION.findall(text)))
                    claim_type = _classify(text, citation_keys)
                    requires_citation = claim_type in {
                        ClaimType.FACTUAL,
                        ClaimType.SYNTHESIS,
                    }
                    claims.append(
                        AtomicClaim.create(
                            run_id=run_id,
                            draft_version=draft_version,
                            text=text,
                            claim_type=claim_type,
                            citation_keys=citation_keys,
                            section=paragraph_section,
                            paragraph_index=paragraph_number,
                            sentence_index=sentence_number * 100 + clause_number,
                            requires_citation=requires_citation,
                        )
                    )
        return tuple(claims)


def _split_sentences(paragraph: str) -> list[str]:
    protected = re.sub(r"\bet al\.\s*", "et al<PERIOD> ", paragraph)
    protected = re.sub(r"\be\.g\.\s*", "e<PERIOD>g<PERIOD> ", protected)
    parts = _SENTENCE_BOUNDARY.split(protected)
    return [part.replace("<PERIOD>", ".") for part in parts]


def _split_atomic_clauses(sentence: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(
            r"\s*;\s+|,\s+(?:but|whereas|while)\s+",
            sentence,
            flags=re.IGNORECASE,
        )
        if clause.strip()
    ]


def _classify(text: str, citation_keys: tuple[str, ...]) -> ClaimType:
    if len(citation_keys) > 1:
        return ClaimType.SYNTHESIS
    if citation_keys or _FACTUAL_CUES.search(text) or re.search(r"\b\d+(?:\.\d+)?%?\b", text):
        return ClaimType.FACTUAL
    if _SCOPE_CUES.search(text):
        return ClaimType.SCOPE
    if _OPINION_CUES.search(text):
        return ClaimType.OPINION
    if _TRANSITION_CUES.search(text) or len(text.split()) < 6:
        return ClaimType.TRANSITION
    return ClaimType.OPINION


def _is_reference_entry(text: str) -> bool:
    return bool(re.match(r"^\[[a-z][a-z0-9_-]+\]\s", text))


__all__ = ["ClaimExtractor"]
