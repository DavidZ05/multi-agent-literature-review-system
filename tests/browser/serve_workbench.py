# ruff: noqa: E402

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.literature_review.cli import run_workbench
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench.server import _DEFAULT_STATIC_ROOT


def _seed_capture_data(store: SQLiteWorkflowStore) -> None:
    topics = (
        "Agent Memory Reliability",
        "Long-Term Memory Evaluation",
        "Multi-Agent Orchestration",
        "Embodied Agent Memory",
    )
    for index, topic in enumerate(topics, start=1):
        timestamp = f"2026-10-0{index}T09:00:00+00:00"
        run = replace(
            ResearchRun.create(topic),
            status=RunStatus.COMPLETED,
            current_stage=WorkflowStage.COMPLETED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        store.create_run(run)

    timestamp = "2026-10-08T09:00:00+00:00"
    selected = replace(
        ResearchRun.create("Memory-Augmented LLM Agents"),
        status=RunStatus.WAITING,
        current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
        created_at=timestamp,
        updated_at=timestamp,
    )
    store.create_run(selected)

    papers = json.loads((PROJECT_ROOT / "data" / "papers.json").read_text(encoding="utf-8"))
    for index, paper in enumerate((papers[5], papers[10], papers[12]), start=1):
        arxiv_id = paper["url"].rsplit("/", 1)[-1]
        store.upsert_candidate(
            selected.run_id,
            CandidatePaper(
                candidate_id=f"capture_candidate_{index}",
                title=paper["title"],
                authors=tuple(paper["authors"]),
                year=paper["year"],
                venue=paper["venue"],
                abstract=paper["contribution"],
                doi=None,
                arxiv_id=arxiv_id,
                semantic_scholar_id=None,
                source_urls=(paper["url"],),
                open_access_pdf_url=None,
                provenance=(f"capture:{arxiv_id}",),
                recommendation=ScreeningRecommendation.INCLUDE,
                relevance_score=0.92 - (index * 0.03),
                status=CandidateStatus.PENDING,
            ),
        )


def main() -> int:
    index_template = (_DEFAULT_STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    if "stream-state" not in index_template:
        raise RuntimeError("browser fixture imported stale Workbench static assets")
    port = int(os.environ.get("WORKBENCH_E2E_PORT", "8876"))
    with TemporaryDirectory(prefix="literature-review-e2e-") as temporary:
        root = Path(temporary)
        store = SQLiteWorkflowStore(root / "workflow.db")
        store.initialize()
        if os.environ.get("WORKBENCH_CAPTURE_MODE") == "1":
            _seed_capture_data(store)
        return run_workbench(
            store,
            root / "artifacts",
            host="127.0.0.1",
            port=port,
            open_browser=False,
            default_corpus_path=PROJECT_ROOT / "data" / "papers.json",
        )


if __name__ == "__main__":
    raise SystemExit(main())
