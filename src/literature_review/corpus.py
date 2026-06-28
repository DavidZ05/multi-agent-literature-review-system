from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_TITLE = (
    "Memory-Augmented LLM Agents: Mechanisms, Evaluation, and Reliability "
    "in Multi-Agent Systems"
)


REQUIRED_FIELDS = {
    "citation_key",
    "title",
    "authors",
    "year",
    "venue",
    "url",
    "category",
    "contribution",
    "evidence",
    "tags",
}

__all__ = [
    "PROJECT_TITLE",
    "REQUIRED_FIELDS",
    "load_papers",
    "first_author_last_name",
    "citation_label",
]


def load_papers(path: Path) -> list[dict[str, Any]]:
    papers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        raise ValueError("papers.json must contain a list")

    seen: set[str] = set()
    for paper in papers:
        missing = REQUIRED_FIELDS - set(paper)
        if missing:
            raise ValueError(f"{paper.get('title', '<unknown>')} missing {sorted(missing)}")
        key = paper["citation_key"]
        if key in seen:
            raise ValueError(f"duplicate citation_key: {key}")
        seen.add(key)
        if not paper["url"].startswith("https://"):
            raise ValueError(f"{key} has a non-https URL")
        if not isinstance(paper["authors"], list) or not paper["authors"]:
            raise ValueError(f"{key} must have at least one author")
    return papers


def first_author_last_name(paper: dict[str, Any]) -> str:
    return str(paper["authors"][0]).split()[-1]


def citation_label(paper: dict[str, Any]) -> str:
    return f"{first_author_last_name(paper)} et al., {paper['year']} [{paper['citation_key']}]"
