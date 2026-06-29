from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from src.literature_review.base import RuntimeAwareAgent
from src.literature_review.corpus import PROJECT_TITLE

__all__ = ["SearchAgent"]


class SearchAgent(RuntimeAwareAgent):
    """Selects and groups papers from the verified corpus."""

    def run(self, papers: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for paper in papers:
            grouped[paper["category"]].append(paper)

        for category in grouped:
            grouped[category].sort(key=lambda item: (item["year"], item["title"]))

        return {
            "agent": "Search Agent",
            "backend": self.backend_note(),
            "query": PROJECT_TITLE,
            "date": date.today().isoformat(),
            "records_identified": len(papers),
            "records_included": len(papers),
            "inclusion_criteria": [
                "Directly addresses LLM agent memory mechanisms, management, or evaluation.",
                "Provides a reusable design pattern, benchmark, or empirical finding.",
                "Has a stable arXiv or publisher URL for reference verification.",
            ],
            "grouped_papers": grouped,
        }
