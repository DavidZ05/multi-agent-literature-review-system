from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re

from src.literature_review.documents.models import DocumentRecord, DocumentStatus
from src.literature_review.models import utc_now_iso


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str
    char_start: int
    char_end: int

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ParsedDocument:
    document: DocumentRecord
    pages: tuple[ParsedPage, ...]
    quality_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "document": self.document.to_dict(),
            "pages": [page.to_dict() for page in self.pages],
            "quality_warnings": list(self.quality_warnings),
        }


class PDFParser:
    NAME = "pdfplumber"

    def __init__(
        self,
        *,
        minimum_quality: float = 0.55,
        minimum_page_characters: int = 80,
    ) -> None:
        if not 0.0 <= minimum_quality <= 1.0:
            raise ValueError("minimum_quality must be between 0 and 1")
        if minimum_page_characters < 1:
            raise ValueError("minimum_page_characters must be positive")
        self.minimum_quality = minimum_quality
        self.minimum_page_characters = minimum_page_characters

    def parse(self, document: DocumentRecord, path: Path) -> ParsedDocument:
        if document.status != DocumentStatus.ACQUIRED:
            raise ValueError("only acquired documents can be parsed")
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "PDF parsing requires pdfplumber; reinstall the project dependencies"
            ) from exc

        pages: list[ParsedPage] = []
        cursor = 0
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            for number, page in enumerate(pdf.pages, start=1):
                text = _normalize_page_text(page.extract_text() or "")
                pages.append(
                    ParsedPage(
                        page_number=number,
                        text=text,
                        char_start=cursor,
                        char_end=cursor + len(text),
                    )
                )
                cursor += len(text) + 1

        quality, warnings = self._quality(pages)
        status = (
            DocumentStatus.PARSED
            if quality >= self.minimum_quality
            else DocumentStatus.LOW_QUALITY
        )
        parsed = replace(
            document,
            status=status,
            parser=self.NAME,
            parser_version=_package_version("pdfplumber"),
            parse_quality=quality,
            page_count=page_count,
            parsed_at=utc_now_iso(),
            error_code="low_text_quality" if status == DocumentStatus.LOW_QUALITY else None,
        )
        return ParsedDocument(parsed, tuple(pages), tuple(warnings))

    def _quality(self, pages: list[ParsedPage]) -> tuple[float, list[str]]:
        if not pages:
            return 0.0, ["document_has_no_pages"]
        readable = sum(
            1 for page in pages if len(page.text) >= self.minimum_page_characters
        )
        total_characters = sum(len(page.text) for page in pages)
        replacement_characters = sum(page.text.count("\ufffd") for page in pages)
        coverage = readable / len(pages)
        density = min(1.0, total_characters / (len(pages) * 500))
        cleanliness = 1.0 - min(
            1.0,
            replacement_characters / max(1, total_characters) * 100,
        )
        quality = round(0.55 * coverage + 0.30 * density + 0.15 * cleanliness, 4)
        warnings: list[str] = []
        if coverage < 0.75:
            warnings.append("many_pages_have_little_extractable_text")
        if density < 0.4:
            warnings.append("low_text_density")
        if cleanliness < 0.9:
            warnings.append("text_contains_many_replacement_characters")
        return quality, warnings


def _normalize_page_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


__all__ = ["PDFParser", "ParsedDocument", "ParsedPage"]
