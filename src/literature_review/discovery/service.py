from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable, Iterable, Mapping

from src.literature_review.discovery.deduplication import deduplicate_papers
from src.literature_review.discovery.planner import QueryPlanner
from src.literature_review.discovery.screening import screen_candidate
from src.literature_review.models import (
    CandidatePaper,
    DiscoveryAttempt,
    ResearchRun,
    utc_now_iso,
)
from src.literature_review.providers.base import SearchProvider
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore


class AllProvidersFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryOutcome:
    candidates: tuple[CandidatePaper, ...]
    failed_providers: tuple[str, ...]
    output_artifacts: Mapping[str, Any]
    attempt: DiscoveryAttempt
    cancelled: bool = False


class DiscoveryService:
    def __init__(
        self,
        planner: QueryPlanner,
        providers: Mapping[str, SearchProvider],
        *,
        query_texts: Iterable[str] = (),
    ) -> None:
        self.planner = planner
        self.providers = dict(providers)
        self.query_texts = tuple(query_texts)

    def run(
        self,
        run: ResearchRun,
        artifact_store: LocalArtifactStore,
        workflow_store: SQLiteWorkflowStore,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> DiscoveryOutcome:
        del artifact_store
        planned_texts = tuple(self.query_texts) or self.planner.suggest(run.topic)
        attempt = DiscoveryAttempt.create(
            run.run_id,
            tuple(self.providers),
            planned_texts,
            self.planner.max_results,
        )
        workflow_store.put_discovery_attempt(attempt)
        workflow_store.append_event(
            run.run_id,
            "discovery_attempt_started",
            {
                "attempt_id": attempt.attempt_id,
                "providers": list(attempt.providers),
                "query_texts": list(attempt.query_texts),
                "max_results": attempt.max_results,
            },
            run.current_stage,
        )
        queries = self.planner.plan(
            run.topic,
            tuple(self.providers),
            query_texts=planned_texts,
            attempt_id=attempt.attempt_id,
        )
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
                {
                    "query_id": query.query_id,
                    "attempt_id": attempt.attempt_id,
                    "provider": query.provider,
                },
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
                        "attempt_id": attempt.attempt_id,
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
                    "attempt_id": attempt.attempt_id,
                    "provider": query.provider,
                    "result_count": len(result.papers),
                },
                run.current_stage,
            )

        if not succeeded and not cancelled:
            failed_attempt = replace(
                attempt,
                status="failed",
                failed_providers=tuple(sorted(failed)),
                completed_at=utc_now_iso(),
            )
            workflow_store.put_discovery_attempt(failed_attempt)
            workflow_store.append_event(
                run.run_id,
                "discovery_attempt_completed",
                failed_attempt.to_dict(),
                run.current_stage,
            )
            raise AllProvidersFailedError("all literature providers failed")

        candidates, ambiguous = deduplicate_papers(papers)
        existing_ids = {
            candidate.candidate_id
            for candidate in workflow_store.list_candidates(run.run_id)
        }
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
        completed_attempt = replace(
            attempt,
            status=("cancelled" if cancelled else "partial" if failed else "succeeded"),
            raw_result_count=len(papers),
            normalized_count=len(papers),
            deduplicated_count=len(candidates),
            screened_count=len(screened),
            new_candidate_count=sum(
                1 for candidate in screened if candidate.candidate_id not in existing_ids
            ),
            failed_providers=tuple(sorted(failed)),
            completed_at=utc_now_iso(),
        )
        workflow_store.put_discovery_attempt(completed_attempt)
        workflow_store.append_event(
            run.run_id,
            "discovery_attempt_completed",
            completed_attempt.to_dict(),
            run.current_stage,
        )
        candidate_payload = {
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
            "attempt": completed_attempt.to_dict(),
        }
        artifacts["discovery/candidates.json"] = candidate_payload
        artifacts[
            f"discovery/attempts/{attempt.attempt_id}/summary.json"
        ] = candidate_payload
        return DiscoveryOutcome(
            tuple(screened),
            tuple(sorted(failed)),
            artifacts,
            completed_attempt,
            cancelled,
        )


__all__ = [
    "AllProvidersFailedError",
    "DiscoveryOutcome",
    "DiscoveryService",
]
