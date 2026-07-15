from __future__ import annotations

import hashlib
from collections.abc import Iterable

from src.literature_review.models import SearchQuery
from src.literature_review.discovery.normalization import normalize_space


class QueryPlanner:
    _FACETS = (
        "",
        "survey",
        "evaluation",
        "reliability",
    )

    def __init__(self, max_results: int = 20) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self.max_results = max_results

    def plan(
        self,
        topic: str,
        providers: tuple[str, ...],
        *,
        query_texts: Iterable[str] = (),
        attempt_id: str | None = None,
    ) -> tuple[SearchQuery, ...]:
        queries = []
        seen: set[tuple[str, str]] = set()
        custom = tuple(
            dict.fromkeys(
                normalized
                for text in query_texts
                if (normalized := normalize_space(text))
            )
        )
        planned_texts = custom or self.suggest(topic)
        for provider in providers:
            for text in planned_texts:
                identity = (provider, text.lower())
                if identity in seen:
                    continue
                seen.add(identity)
                digest = hashlib.sha256(
                    f"{provider}\0{text}\0{attempt_id or ''}".encode("utf-8")
                ).hexdigest()[:16]
                queries.append(
                    SearchQuery(
                        query_id=f"query_{digest}",
                        text=text,
                        provider=provider,
                        max_results=self.max_results,
                        year_from=None,
                        year_to=None,
                        attempt_id=attempt_id,
                    )
                )
        return tuple(queries)

    @classmethod
    def suggest(cls, topic: str) -> tuple[str, ...]:
        return tuple(
            normalize_space(f"{topic} {facet}") for facet in cls._FACETS
        )


__all__ = ["QueryPlanner"]
