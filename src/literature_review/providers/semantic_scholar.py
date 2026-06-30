from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import re
import time
from urllib.parse import quote, urlencode

from src.literature_review.models import (
    ProviderPaper,
    ProviderSearchResult,
    SearchQuery,
)
from src.literature_review.providers.base import ResponseCache
from src.literature_review.providers.http import HttpTransport


class SemanticScholarProvider:
    provider_id = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1"
    fields = "title,abstract,year,venue,authors,externalIds,url,openAccessPdf"

    def __init__(
        self,
        transport: HttpTransport,
        cache: ResponseCache,
        *,
        api_key: str = "",
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.cache = cache
        self.api_key = api_key
        self.clock = clock
        self.sleeper = sleeper
        self._last_uncached_request: float | None = None

    def search(self, query: SearchQuery) -> ProviderSearchResult:
        if query.provider != self.provider_id:
            raise ValueError(
                "Semantic Scholar provider received a query for another provider"
            )
        parameters = urlencode(
            {
                "query": query.text,
                "limit": min(max(query.max_results, 1), 100),
                "fields": self.fields,
            }
        )
        url = f"{self.endpoint}/paper/search?{parameters}"
        return self._request(query.query_id, url, list_key="data")

    def fetch_details(self, provider_id: str) -> ProviderPaper:
        url = (
            f"{self.endpoint}/paper/{quote(provider_id, safe='')}?"
            f"{urlencode({'fields': self.fields})}"
        )
        result = self._request(f"details_{provider_id}", url, list_key=None)
        if not result.papers:
            raise LookupError(provider_id)
        return result.papers[0]

    def _request(
        self,
        query_id: str,
        url: str,
        *,
        list_key: str | None,
    ) -> ProviderSearchResult:
        cache_key = (
            "semantic_scholar:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
        )
        body = self.cache.get(cache_key)
        response_headers: dict[str, str] = {}
        if body is None:
            now = self.clock()
            if self._last_uncached_request is not None:
                delay = 1.0 - (now - self._last_uncached_request)
                if delay > 0:
                    self.sleeper(delay)
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            response = self.transport.get(url, headers)
            body = response.body
            response_headers = dict(response.headers)
            self.cache.put(cache_key, body, 24 * 60 * 60)
            self._last_uncached_request = self.clock()

        payload = json.loads(body)
        records = [payload] if list_key is None else payload.get(list_key, [])
        return ProviderSearchResult(
            provider=self.provider_id,
            query_id=query_id,
            request_url=url,
            papers=tuple(self._paper(record) for record in records),
            raw_body=body,
            response_headers=response_headers,
        )

    def _paper(self, record: dict[str, object]) -> ProviderPaper:
        external_ids = record.get("externalIds") or {}
        assert isinstance(external_ids, dict)
        open_access = record.get("openAccessPdf") or {}
        assert isinstance(open_access, dict)
        authors = record.get("authors") or []
        assert isinstance(authors, list)
        paper_id = str(record["paperId"])
        arxiv_id = external_ids.get("ArXiv")
        return ProviderPaper(
            provider=self.provider_id,
            provider_id=paper_id,
            title=self._space(str(record["title"])),
            authors=tuple(
                self._space(str(author["name"]))
                for author in authors
                if isinstance(author, dict) and author.get("name")
            ),
            year=record.get("year"),
            venue=(
                None if not record.get("venue") else self._space(str(record["venue"]))
            ),
            abstract=(
                None
                if record.get("abstract") is None
                else self._space(str(record["abstract"]))
            ),
            doi=(
                None
                if not external_ids.get("DOI")
                else str(external_ids["DOI"]).lower()
            ),
            arxiv_id=(None if not arxiv_id else re.sub(r"v\d+$", "", str(arxiv_id))),
            semantic_scholar_id=paper_id,
            source_url=str(
                record.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"
            ),
            open_access_pdf_url=(
                None if not open_access.get("url") else str(open_access["url"])
            ),
        )

    @staticmethod
    def _space(value: str) -> str:
        return " ".join(value.split())


__all__ = ["SemanticScholarProvider"]
