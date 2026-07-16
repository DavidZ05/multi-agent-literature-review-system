from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
from uuid import uuid4

from src.literature_review.models import utc_now_iso


_RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}")
_CHUNK_ID = re.compile(r"chunk_[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validate_utc_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


class DocumentStatus(str, Enum):
    ACQUIRED = "acquired"
    PARSED = "parsed"
    LOW_QUALITY = "low_quality"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    run_id: str
    citation_key: str
    source_url: str
    status: DocumentStatus
    access_method: str
    retrieved_at: str
    relative_path: str | None = None
    sha256: str | None = None
    media_type: str | None = None
    byte_size: int = 0
    parser: str | None = None
    parser_version: str | None = None
    parse_quality: float | None = None
    page_count: int = 0
    parsed_at: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not _DOCUMENT_ID.fullmatch(self.document_id):
            raise ValueError("document_id must match doc_ + 32 lowercase hex characters")
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must match run_ + 32 lowercase hex characters")
        if not self.citation_key.strip() or not self.source_url.strip():
            raise ValueError("citation_key and source_url must be nonblank")
        if not isinstance(self.status, DocumentStatus):
            raise TypeError("status must be a DocumentStatus")
        if self.access_method not in {"downloaded", "imported", "none"}:
            raise ValueError("invalid document access_method")
        _validate_utc_timestamp(self.retrieved_at, "retrieved_at")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ValueError("byte_size must be a nonnegative integer")
        if not isinstance(self.page_count, int) or isinstance(self.page_count, bool) or self.page_count < 0:
            raise ValueError("page_count must be a nonnegative integer")
        if self.parse_quality is not None:
            if isinstance(self.parse_quality, bool) or not isinstance(
                self.parse_quality, (int, float)
            ) or not 0.0 <= self.parse_quality <= 1.0:
                raise ValueError("parse_quality must be between 0 and 1")
        if self.sha256 is not None and not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must contain 64 lowercase hex characters")
        if self.relative_path is not None:
            path = PurePosixPath(self.relative_path)
            if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("documents",):
                raise ValueError("relative_path must stay under documents/")
        if self.status in {
            DocumentStatus.ACQUIRED,
            DocumentStatus.PARSED,
            DocumentStatus.LOW_QUALITY,
        } and any(
            value is None for value in (self.relative_path, self.sha256, self.media_type)
        ):
            raise ValueError("acquired documents require path, checksum, and media type")
        if self.status in {DocumentStatus.PARSED, DocumentStatus.LOW_QUALITY}:
            if not self.parser or not self.parser_version or not self.parsed_at:
                raise ValueError("parsed documents require parser metadata")
            _validate_utc_timestamp(self.parsed_at, "parsed_at")

    @classmethod
    def acquired(
        cls,
        run_id: str,
        citation_key: str,
        source_url: str,
        *,
        relative_path: str,
        sha256: str,
        byte_size: int,
        access_method: str,
    ) -> DocumentRecord:
        return cls(
            document_id=f"doc_{uuid4().hex}",
            run_id=run_id,
            citation_key=citation_key,
            source_url=source_url,
            status=DocumentStatus.ACQUIRED,
            access_method=access_method,
            retrieved_at=utc_now_iso(),
            relative_path=relative_path,
            sha256=sha256,
            media_type="application/pdf",
            byte_size=byte_size,
        )

    @classmethod
    def unavailable(
        cls,
        run_id: str,
        citation_key: str,
        source_url: str,
        error_code: str,
    ) -> DocumentRecord:
        return cls(
            document_id=f"doc_{uuid4().hex}",
            run_id=run_id,
            citation_key=citation_key,
            source_url=source_url,
            status=DocumentStatus.UNAVAILABLE,
            access_method="none",
            retrieved_at=utc_now_iso(),
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DocumentRecord:
        values = dict(data)
        values["status"] = DocumentStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    run_id: str
    document_id: str
    citation_key: str
    section: str | None
    page_start: int
    page_end: int
    text: str
    token_count: int
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if not _CHUNK_ID.fullmatch(self.chunk_id):
            raise ValueError("chunk_id must match chunk_ + 32 lowercase hex characters")
        if not _RUN_ID.fullmatch(self.run_id) or not _DOCUMENT_ID.fullmatch(
            self.document_id
        ):
            raise ValueError("invalid run_id or document_id")
        if not self.citation_key.strip() or not self.text.strip():
            raise ValueError("citation_key and text must be nonblank")
        numeric_fields = (
            self.page_start,
            self.page_end,
            self.token_count,
            self.char_start,
            self.char_end,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in numeric_fields):
            raise ValueError("evidence page, token, and offset fields must be integers")
        if self.page_start < 1 or self.page_end < self.page_start:
            raise ValueError("evidence pages must be positive and ordered")
        if self.token_count < 1:
            raise ValueError("token_count must be positive")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("character offsets must be nonnegative and ordered")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        document_id: str,
        document_sha256: str,
        citation_key: str,
        section: str | None,
        page_start: int,
        page_end: int,
        text: str,
        char_start: int,
        char_end: int,
        settings_fingerprint: str,
    ) -> EvidenceChunk:
        identity = "\0".join(
            (
                document_sha256,
                str(page_start),
                str(page_end),
                str(char_start),
                str(char_end),
                settings_fingerprint,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return cls(
            chunk_id=f"chunk_{digest}",
            run_id=run_id,
            document_id=document_id,
            citation_key=citation_key,
            section=section,
            page_start=page_start,
            page_end=page_end,
            text=text.strip(),
            token_count=len(re.findall(r"\S+", text)),
            char_start=char_start,
            char_end=char_end,
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvidenceChunk:
        return cls(**dict(data))


__all__ = ["DocumentRecord", "DocumentStatus", "EvidenceChunk"]
