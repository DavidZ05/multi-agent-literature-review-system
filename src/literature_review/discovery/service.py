from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable, Mapping

from src.literature_review.discovery.deduplication import deduplicate_papers
from src.literature_review.discovery.planner import QueryPlanner
from src.literature_review.discovery.screening import screen_candidate
from src.literature_review.models import CandidatePaper, ResearchRun
from src.literature_review.providers.base import SearchProvider
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore


class AllProvidersFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryOutcome:
    candidates: tuple[CandidatePaper, ...]
    failed_providers: tuple[str, ...]
    output_artifacts: Mapping[str, Any]


class DiscoveryService:
    def __init__(
        self,
        planner: QueryPlanner,
        providers: Mapping[str, SearchProvider],
    ) -> None:
        self.planner = planner
        self.providers = dict(providers)

    def run(
        self,
        run: ResearchRun,
        artifact_store: LocalArtifactStore,
        workflow_store: SQLiteWorkflowStore,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> DiscoveryOutcome:
        del artifact_store
        queries = self.planner.plan(run.topic, tuple(self.providers))
        papers = []
        failed: set[str] = set()
        succeeded: set[str] = set()
        artifacts: dict[str, Any] = {}
        cancelled = False
        for query in queries:
            if cancellation_check is not None and cancellation_check():
                cancelled = True
                break
            workflow_store.save_search_query(run.run_id, query)
            workflow_store.append_event(
                run.run_id,
                "query_started",
                {"query_id": query.query_id, "provider": query.provider},
                run.current_stage,
            )
            try:
                result = self.providers[query.provider].search(query)
            except Exception as exc:
                failed.add(query.provider)
                workflow_store.append_event(
                    run.run_id,
                    "provider_failed",
                    {
                        "query_id": query.query_id,
                        "provider": query.provider,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    run.current_stage,
                )
                continue
            succeeded.add(query.provider)
            papers.extend(result.papers)
            extension = getattr(
                self.providers[query.provider],
                "artifact_extension",
                "json",
            )
            if not isinstance(extension, str) or not re.fullmatch(
                r"[a-z0-9]{1,10}", extension
            ):
                raise ValueError("provider artifact_extension is invalid")
            artifacts[
                f"discovery/raw/{query.provider}/{query.query_id}.{extension}"
            ] = result.raw_body.decode("utf-8", errors="replace")
            workflow_store.append_event(
                run.run_id,
                "query_completed",
                {
                    "query_id": query.query_id,
                    "provider": query.provider,
                    "result_count": len(result.papers),
                },
                run.current_stage,
            )

        if not succeeded and not cancelled:
            raise AllProvidersFailedError("all literature providers failed")

        candidates, ambiguous = deduplicate_papers(papers)
        screened = []
        for candidate in candidates:
            result = screen_candidate(
                candidate,
                topic=run.topic,
                coverage_gap_terms=(
                    "mechanism",
                    "evaluation",
                    "reliability",
                    "multi-agent",
                ),
                seed_title_keys=(),
            )
            updated = replace(
                candidate,
                recommendation=result.recommendation,
                relevance_score=result.score,
            )
            workflow_store.upsert_candidate(run.run_id, updated)
            screened.append(updated)
        artifacts["discovery/candidates.json"] = {
            "candidates": [item.to_dict() for item in screened],
            "ambiguous_matches": [
                {
                    "candidate_id": item.candidate_id,
                    "provider_id": item.provider_id,
                    "reason": item.reason,
                }
                for item in ambiguous
            ],
            "failed_providers": sorted(failed),
        }
        return DiscoveryOutcome(
            tuple(screened),
            tuple(sorted(failed)),
            artifacts,
        )


__all__ = [
    "AllProvidersFailedError",
    "DiscoveryOutcome",
    "DiscoveryService",
]
