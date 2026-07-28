from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import socket
from typing import Mapping
from urllib.parse import urlparse

from src.literature_review.documents.models import DocumentRecord
from src.literature_review.providers.http import (
    HttpTransport,
    ProviderRequestError,
    UrllibHttpTransport,
)
from src.literature_review.storage import LocalArtifactStore


_ARXIV_PATH = re.compile(r"^/(?:abs|pdf)/([^/?#]+?)(?:\.pdf)?$")


class DocumentAcquisitionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AcquisitionResult:
    document: DocumentRecord
    downloaded: bool


def resolve_pdf_url(paper: Mapping[str, object]) -> str:
    explicit = paper.get("open_access_pdf_url")
    source = explicit if isinstance(explicit, str) and explicit.strip() else paper.get("url")
    if not isinstance(source, str) or not source.strip():
        raise DocumentAcquisitionError("paper has no source URL", code="missing_url")
    parsed = urlparse(source.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise DocumentAcquisitionError(
            "document acquisition requires an HTTPS URL",
            code="unsafe_url",
        )
    _reject_local_host(parsed.hostname)
    if parsed.hostname.lower() in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = _ARXIV_PATH.fullmatch(parsed.path)
        if match:
            return f"https://arxiv.org/pdf/{match.group(1)}.pdf"
    return source.strip()


class DocumentAcquirer:
    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        max_pdf_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        if max_pdf_bytes < 1:
            raise ValueError("max_pdf_bytes must be positive")
        self.transport = transport or UrllibHttpTransport(
            timeout_seconds=15,
            max_attempts=1,
            max_response_bytes=max_pdf_bytes,
            url_validator=_validate_public_https_url,
        )
        self.max_pdf_bytes = max_pdf_bytes

    def acquire(
        self,
        run_id: str,
        paper: Mapping[str, object],
        artifact_store: LocalArtifactStore,
    ) -> AcquisitionResult:
        citation_key = str(paper.get("citation_key", "")).strip()
        if not citation_key:
            raise DocumentAcquisitionError(
                "paper has no citation key",
                code="missing_citation_key",
            )
        try:
            source_url = resolve_pdf_url(paper)
            response = self.transport.get(
                source_url,
                {"Accept": "application/pdf"},
            )
            final_url = response.final_url or source_url
            final_parsed = urlparse(final_url)
            if final_parsed.scheme != "https" or not final_parsed.hostname:
                raise DocumentAcquisitionError(
                    "document redirect did not preserve HTTPS",
                    code="unsafe_redirect",
                )
            _reject_local_host(final_parsed.hostname)
            if response.status < 200 or response.status >= 300:
                raise DocumentAcquisitionError(
                    f"document request returned HTTP {response.status}",
                    code=f"http_{response.status}",
                )
            content_type = next(
                (
                    value
                    for key, value in response.headers.items()
                    if key.lower() == "content-type"
                ),
                "",
            ).split(";", 1)[0].strip().lower()
            if len(response.body) > self.max_pdf_bytes:
                raise DocumentAcquisitionError(
                    "document exceeded the configured size limit",
                    code="pdf_too_large",
                )
            if not response.body.startswith(b"%PDF-"):
                suffix = "" if content_type == "application/pdf" else f" ({content_type or 'unknown type'})"
                raise DocumentAcquisitionError(
                    f"document response is not a PDF{suffix}",
                    code="not_pdf",
                )
        except ProviderRequestError as exc:
            return AcquisitionResult(
                DocumentRecord.unavailable(
                    run_id,
                    citation_key,
                    paper_source_url(paper),
                    exc.code,
                ),
                False,
            )
        except DocumentAcquisitionError as exc:
            return AcquisitionResult(
                DocumentRecord.unavailable(
                    run_id,
                    citation_key,
                    paper_source_url(paper),
                    exc.code,
                ),
                False,
            )

        relative_path = f"documents/{_safe_filename(citation_key)}.pdf"
        artifact = artifact_store.write_bytes(run_id, relative_path, response.body)
        return AcquisitionResult(
            DocumentRecord.acquired(
                run_id,
                citation_key,
                source_url,
                relative_path=relative_path,
                sha256=artifact.sha256,
                byte_size=artifact.size_bytes,
                access_method="downloaded",
            ),
            True,
        )

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        content: bytes,
        artifact_store: LocalArtifactStore,
        *,
        source_label: str = "https://local.invalid/imported-pdf",
        relative_path: str | None = None,
    ) -> DocumentRecord:
        if len(content) > self.max_pdf_bytes:
            raise DocumentAcquisitionError(
                "document exceeded the configured size limit",
                code="pdf_too_large",
            )
        if not content.startswith(b"%PDF-"):
            raise DocumentAcquisitionError("imported file is not a PDF", code="not_pdf")
        relative_path = relative_path or document_relative_path(citation_key)
        artifact = artifact_store.write_bytes(run_id, relative_path, content)
        return DocumentRecord.acquired(
            run_id,
            citation_key,
            source_label,
            relative_path=relative_path,
            sha256=artifact.sha256,
            byte_size=artifact.size_bytes,
            access_method="imported",
        )


def paper_source_url(paper: Mapping[str, object]) -> str:
    value = paper.get("open_access_pdf_url") or paper.get("url")
    return value.strip() if isinstance(value, str) and value.strip() else "https://unavailable.invalid/"


def _safe_filename(citation_key: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", citation_key).strip("._")
    if not normalized:
        raise DocumentAcquisitionError("citation key has no safe filename", code="unsafe_citation_key")
    return normalized[:120]


def document_relative_path(citation_key: str) -> str:
    return f"documents/{_safe_filename(citation_key)}.pdf"


def _reject_local_host(hostname: str) -> None:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise DocumentAcquisitionError(
            "document URL cannot target localhost",
            code="unsafe_url",
        )
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return
    if not address.is_global:
        raise DocumentAcquisitionError(
            "document URL cannot target a non-public IP address",
            code="unsafe_url",
        )


def _validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DocumentAcquisitionError(
            "document acquisition requires a public HTTPS URL",
            code="unsafe_url",
        )
    _reject_local_host(parsed.hostname)
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise DocumentAcquisitionError(
            "document hostname could not be resolved",
            code="dns_failed",
        ) from exc
    if not addresses:
        raise DocumentAcquisitionError(
            "document hostname did not resolve to an address",
            code="dns_failed",
        )
    for address in addresses:
        _reject_local_host(address)


__all__ = [
    "AcquisitionResult",
    "DocumentAcquirer",
    "DocumentAcquisitionError",
    "document_relative_path",
    "resolve_pdf_url",
]
