from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from src.literature_review.documents.models import EvidenceChunk
from src.literature_review.documents.parser import ParsedDocument, ParsedPage


@dataclass(frozen=True)
class ChunkingConfig:
    target_words: int = 420
    overlap_words: int = 60

    def __post_init__(self) -> None:
        if self.target_words < 100:
            raise ValueError("target_words must be at least 100")
        if self.overlap_words < 0 or self.overlap_words >= self.target_words:
            raise ValueError("overlap_words must be nonnegative and below target_words")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(dict(self.__dict__), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvidenceIndexer:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def build(self, parsed: ParsedDocument) -> tuple[EvidenceChunk, ...]:
        document = parsed.document
        if document.sha256 is None:
            raise ValueError("parsed document has no checksum")
        units = self._units(parsed.pages)
        chunks: list[EvidenceChunk] = []
        start = 0
        while start < len(units):
            end = min(len(units), start + self.config.target_words)
            window = units[start:end]
            if not window:
                break
            text = " ".join(unit[0] for unit in window).strip()
            if text:
                chunks.append(
                    EvidenceChunk.create(
                        run_id=document.run_id,
                        document_id=document.document_id,
                        document_sha256=document.sha256,
                        citation_key=document.citation_key,
                        section=_section_for(window),
                        page_start=min(unit[1] for unit in window),
                        page_end=max(unit[1] for unit in window),
                        text=text,
                        char_start=window[0][2],
                        char_end=window[-1][3],
                        settings_fingerprint=self.config.fingerprint,
                    )
                )
            if end == len(units):
                break
            start = end - self.config.overlap_words
        return tuple(chunks)

    @staticmethod
    def _units(pages: tuple[ParsedPage, ...]) -> list[tuple[str, int, int, int, str | None]]:
        units: list[tuple[str, int, int, int, str | None]] = []
        current_section: str | None = None
        for page in pages:
            local_cursor = 0
            for line in page.text.splitlines():
                stripped = line.strip()
                if _looks_like_heading(stripped):
                    current_section = stripped[:160]
                for match in re.finditer(r"\S+", line):
                    start = page.char_start + local_cursor + match.start()
                    end = page.char_start + local_cursor + match.end()
                    units.append(
                        (match.group(0), page.page_number, start, end, current_section)
                    )
                local_cursor += len(line) + 1
        return units


def _looks_like_heading(line: str) -> bool:
    if not line or len(line) > 120 or len(line.split()) > 14:
        return False
    return bool(
        re.match(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,:()/-]+$", line)
        and not line.endswith((".", ";"))
    )


def _section_for(window: list[tuple[str, int, int, int, str | None]]) -> str | None:
    return next((unit[4] for unit in reversed(window) if unit[4]), None)


__all__ = ["ChunkingConfig", "EvidenceIndexer"]
