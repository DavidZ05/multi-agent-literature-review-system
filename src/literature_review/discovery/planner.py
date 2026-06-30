from __future__ import annotations

import hashlib

from src.literature_review.models import SearchQuery
from src.literature_review.discovery.normalization import normalize_space


class QueryPlanner:
    _FACETS = (
        "core memory mechanism",
        "evaluation benchmark",
        "reliability failure",
        "multi-agent memory",
    )

    def __init__(self, max_results: int = 20) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self.max_results = max_results

    def plan(
        self,
        topic: str,
        providers: tuple[str, ...],
    ) -> tuple[SearchQuery, ...]:
        queries = []
        seen: set[tuple[str, str]] = set()
        for provider in providers:
            for facet in self._FACETS:
                text = normalize_space(f"{topic} {facet}")
                identity = (provider, text.lower())
                if identity in seen:
                    continue
                seen.add(identity)
                digest = hashlib.sha256(
                    f"{provider}\0{text}".encode("utf-8")
                ).hexdigest()[:16]
                queries.append(
                    SearchQuery(
                        query_id=f"query_{digest}",
                        text=text,
                        provider=provider,
                        max_results=self.max_results,
                        year_from=None,
                        year_to=None,
                    )
                )
        return tuple(queries)


__all__ = ["QueryPlanner"]
