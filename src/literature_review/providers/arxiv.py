from __future__ import annotations

from collections.abc import Callable
import hashlib
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from src.literature_review.models import (
    ProviderPaper,
    ProviderSearchResult,
    SearchQuery,
)
from src.literature_review.providers.base import ResponseCache
from src.literature_review.providers.http import HttpTransport


class ArxivProvider:
    provider_id = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"
    _ATOM = "http://www.w3.org/2005/Atom"
    _ARXIV = "http://arxiv.org/schemas/atom"

    def __init__(
        self,
        transport: HttpTransport,
        cache: ResponseCache,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.cache = cache
        self.clock = clock
        self.sleeper = sleeper
        self._last_uncached_request: float | None = None

    def search(self, query: SearchQuery) -> ProviderSearchResult:
        if query.provider != self.provider_id:
            raise ValueError("arXiv provider received a query for another provider")
        escaped = query.text.replace("\\", "\\\\").replace('"', '\\"')
        return self._request(
            query.query_id,
            {
                "search_query": f'all:"{escaped}"',
                "start": 0,
                "max_results": min(max(query.max_results, 1), 100),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
        )

    def fetch_details(self, provider_id: str) -> ProviderPaper:
        result = self._request(
            f"details_{provider_id}",
            {"id_list": self._normalize_id(provider_id), "max_results": 1},
        )
        if not result.papers:
            raise LookupError(provider_id)
        return result.papers[0]

    def _request(
        self,
        query_id: str,
        parameters: dict[str, object],
    ) -> ProviderSearchResult:
        url = f"{self.endpoint}?{urlencode(parameters)}"
        cache_key = f"arxiv:{hashlib.sha256(url.encode()).hexdigest()}"
        body = self.cache.get(cache_key)
        headers: dict[str, str] = {}
        if body is None:
            now = self.clock()
            if self._last_uncached_request is not None:
                delay = 3.0 - (now - self._last_uncached_request)
                if delay > 0:
                    self.sleeper(delay)
            response = self.transport.get(url, {"Accept": "application/atom+xml"})
            body = response.body
            headers = dict(response.headers)
            self.cache.put(cache_key, body, 24 * 60 * 60)
            self._last_uncached_request = self.clock()
        return ProviderSearchResult(
            provider=self.provider_id,
            query_id=query_id,
            request_url=url,
            papers=self._parse(body),
            raw_body=body,
            response_headers=headers,
        )

    def _parse(self, body: bytes) -> tuple[ProviderPaper, ...]:
        root = ET.fromstring(body)
        papers = []
        for entry in root.findall(f"{{{self._ATOM}}}entry"):
            source_url = self._text(entry, self._ATOM, "id")
            arxiv_id = self._normalize_id(source_url)
            links = entry.findall(f"{{{self._ATOM}}}link")
            pdf_url = next(
                (
                    link.attrib.get("href")
                    for link in links
                    if link.attrib.get("title") == "pdf"
                ),
                None,
            )
            published = self._text(entry, self._ATOM, "published")
            authors = tuple(
                self._normalize_space(self._text(author, self._ATOM, "name"))
                for author in entry.findall(f"{{{self._ATOM}}}author")
            )
            doi = self._optional_text(entry, self._ARXIV, "doi")
            venue = self._optional_text(entry, self._ARXIV, "journal_ref") or "arXiv"
            papers.append(
                ProviderPaper(
                    provider=self.provider_id,
                    provider_id=arxiv_id,
                    title=self._normalize_space(self._text(entry, self._ATOM, "title")),
                    authors=authors,
                    year=int(published[:4]),
                    venue=self._normalize_space(venue),
                    abstract=self._normalize_space(
                        self._text(entry, self._ATOM, "summary")
                    ),
                    doi=None if doi is None else doi.lower(),
                    arxiv_id=arxiv_id,
                    semantic_scholar_id=None,
                    source_url=source_url,
                    open_access_pdf_url=pdf_url,
                )
            )
        return tuple(papers)

    @staticmethod
    def _normalize_id(value: str) -> str:
        identifier = value.rstrip("/").rsplit("/", 1)[-1]
        return re.sub(r"v\d+$", "", identifier)

    @staticmethod
    def _normalize_space(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _text(element: ET.Element, namespace: str, name: str) -> str:
        child = element.find(f"{{{namespace}}}{name}")
        if child is None or child.text is None:
            raise ValueError(f"arXiv entry missing {name}")
        return child.text

    @classmethod
    def _optional_text(
        cls,
        element: ET.Element,
        namespace: str,
        name: str,
    ) -> str | None:
        child = element.find(f"{{{namespace}}}{name}")
        if child is None or child.text is None:
            return None
        return cls._normalize_space(child.text)


__all__ = ["ArxivProvider"]
