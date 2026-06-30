from __future__ import annotations

from typing import Protocol

from src.literature_review.models import (
    ProviderPaper,
    ProviderSearchResult,
    SearchQuery,
)


class SearchProvider(Protocol):
    provider_id: str

    def search(self, query: SearchQuery) -> ProviderSearchResult: ...

    def fetch_details(self, provider_id: str) -> ProviderPaper: ...


class ResponseCache(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, value: bytes, ttl_seconds: int) -> None: ...


class NullResponseCache:
    def get(self, key: str) -> bytes | None:
        return None

    def put(self, key: str, value: bytes, ttl_seconds: int) -> None:
        return None


__all__ = ["NullResponseCache", "ResponseCache", "SearchProvider"]
