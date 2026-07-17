from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import re

from src.literature_review.discovery import QueryPlanner
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    WorkflowStage,
)
from src.literature_review.storage import LocalArtifactStore


class RuntimeDiagnostics:
    MODEL_BACKED_AGENT_IDS = (
        "writer",
        "domain_expert",
        "structure_mentor",
        "review_synthesizer",
        "polish",
        "evaluation_reflection",
    )

    def __init__(self, artifact_root: Path) -> None:
        self.artifacts = LocalArtifactStore(artifact_root)

    def summarize(
        self,
        run: ResearchRun,
        events: Iterable[object],
    ) -> dict[str, object]:
        config = self._stored_runtime_config(run.run_id)
        agent_settings = config.get("agent_settings", {})
        if not isinstance(agent_settings, dict):
            agent_settings = {}
        backend = str(
            config.get("active_backend")
            or config.get("backend")
            or "deterministic"
        )
        if backend not in {"deterministic", "api"}:
            backend = "deterministic"
        api_mode = str(config.get("api_mode") or "single")
        if api_mode not in {"single", "multi"}:
            api_mode = "single"

        api_enabled_agents: list[str] = []
        model_names: list[str] = []
        for agent_id in self.MODEL_BACKED_AGENT_IDS:
            settings = agent_settings.get(agent_id, {})
            if not isinstance(settings, dict):
                continue
            if settings.get("active_backend") == "api":
                api_enabled_agents.append(agent_id)
                model = settings.get("model")
                if isinstance(model, str) and model and model not in model_names:
                    model_names.append(model)
        if backend != "api":
            model_summary = "deterministic"
            model_names = []
            api_enabled_agents = []
        elif len(model_names) == 1:
            model_summary = "single_model"
        elif len(model_names) > 1:
            model_summary = "multiple_models"
        else:
            model_summary = "api_configured"

        return {
            "backend": backend,
            "api_mode": api_mode,
            "model_summary": model_summary,
            "model_names": model_names,
            "api_enabled_agents": api_enabled_agents,
            "current_executor": self._current_executor(run, backend),
            "safe_error_category": self._safe_error_category(events),
        }

    def stored_request(self, run_id: str) -> dict[str, object]:
        try:
            request = self.artifacts.read_json(
                run_id,
                "inputs/research_request.json",
            )
        except Exception:
            return {}
        return request if isinstance(request, dict) else {}

    def _stored_runtime_config(self, run_id: str) -> dict[str, object]:
        request = self.stored_request(run_id)
        config = request.get("runtime_config", {})
        return config if isinstance(config, dict) else {}

    @staticmethod
    def _current_executor(run: ResearchRun, backend: str) -> str:
        stage = run.current_stage.value
        mapping = {
            "created": "workflow_planner",
            "planning": "workflow_planner",
            "discovering": "literature_discovery",
            "screening": "screening_agent",
            "awaiting_corpus_approval": "human_approval",
            "acquiring_documents": "document_acquisition",
            "indexing_evidence": "evidence_indexing",
            "claim_verification": "claim_verification",
            "awaiting_evidence_review": "human_evidence_review",
            "completed": "completed",
        }
        if stage in {
            "drafting",
            "reviewing",
            "revising",
            "polishing",
            "final_verification",
        }:
            return "model_agent_loop" if backend == "api" else "deterministic_agent_loop"
        return mapping.get(stage, "workflow_engine")

    @staticmethod
    def _safe_error_category(events: Iterable[object]) -> str | None:
        for event in reversed(list(events)):
            event_type = getattr(event, "event_type", "")
            payload = getattr(event, "payload", {})
            message = ""
            if isinstance(payload, Mapping):
                message = str(payload.get("message", ""))
            if event_type == "stage_retry_wait":
                if message.startswith("API provider retryable failure"):
                    return "retryable_api_failure"
                return "retryable_workflow_failure"
            if event_type == "stage_failed":
                if message.startswith("API provider permanent failure"):
                    return "permanent_api_failure"
                return "workflow_failure"
            if event_type in {"discovery_retry_completed", "run_completed"}:
                return None
        return None


class DiscoveryDiagnostics:
    def __init__(self, runtime: RuntimeDiagnostics) -> None:
        self.runtime = runtime

    def summarize(
        self,
        run: ResearchRun,
        candidates: Iterable[CandidatePaper],
        events: Iterable[object],
        attempts: Iterable[object] = (),
    ) -> dict[str, object]:
        event_list = list(events)
        candidate_list = list(candidates)
        attempt_list = list(attempts)
        latest_attempt = attempt_list[-1] if attempt_list else None
        latest_attempt_id = getattr(latest_attempt, "attempt_id", None)
        provider_stats: dict[str, dict[str, object]] = {}
        total_results = 0
        total_failures = 0
        discovery_enabled = bool(attempt_list)
        for event in event_list:
            stage = getattr(event, "stage", None)
            event_type = getattr(event, "event_type", "")
            payload = getattr(event, "payload", {})
            if getattr(stage, "value", stage) == "discovering":
                discovery_enabled = True
            if event_type not in {
                "query_started",
                "query_completed",
                "provider_failed",
            }:
                continue
            if latest_attempt_id is not None:
                if not isinstance(payload, Mapping) or payload.get(
                    "attempt_id"
                ) != latest_attempt_id:
                    continue
            provider = (
                str(payload.get("provider", "")).strip()
                if isinstance(payload, Mapping)
                else ""
            )
            if not provider:
                provider = "unknown"
            stats = provider_stats.setdefault(
                provider,
                {
                    "provider": provider,
                    "queries": 0,
                    "completed_queries": 0,
                    "result_count": 0,
                    "failures": 0,
                    "error_categories": [],
                    "last_error_type": None,
                    "last_error_category": None,
                    "last_error_message": None,
                },
            )
            discovery_enabled = True
            if event_type == "query_started":
                stats["queries"] = int(stats["queries"]) + 1
            elif event_type == "query_completed":
                result_count = 0
                if isinstance(payload, Mapping):
                    result_count = int(payload.get("result_count", 0) or 0)
                stats["completed_queries"] = int(stats["completed_queries"]) + 1
                stats["result_count"] = int(stats["result_count"]) + result_count
                total_results += result_count
            elif event_type == "provider_failed":
                total_failures += 1
                stats["failures"] = int(stats["failures"]) + 1
                if isinstance(payload, Mapping):
                    message = str(payload.get("message", ""))
                    category = self._provider_error_category(message)
                    categories = list(stats["error_categories"])
                    if category not in categories:
                        categories.append(category)
                    stats["error_categories"] = categories
                    stats["last_error_type"] = str(payload.get("error_type", ""))
                    stats["last_error_category"] = category
                    stats["last_error_message"] = message

        candidate_count = len(candidate_list)
        pending_count = sum(
            candidate.status == CandidateStatus.PENDING
            for candidate in candidate_list
        )
        corpus_alignment = self._corpus_alignment(run)
        issue = "not_run"
        if discovery_enabled:
            if run.status == RunStatus.ACTIVE and run.current_stage in {
                WorkflowStage.DISCOVERING,
                WorkflowStage.SCREENING,
            }:
                issue = "running"
            elif run.status == RunStatus.RETRY_WAIT or getattr(
                latest_attempt,
                "status",
                None,
            ) == "failed":
                issue = "provider_failure"
            elif candidate_count == 0:
                issue = "zero_candidates"
            elif total_failures:
                issue = "partial_provider_failure"
            else:
                issue = "ok"
        return {
            "enabled": discovery_enabled,
            "issue": issue,
            "candidate_count": candidate_count,
            "pending_count": pending_count,
            "total_queries": sum(
                int(stats["queries"]) for stats in provider_stats.values()
            ),
            "total_results": total_results,
            "total_failures": total_failures,
            "attempt_count": len(attempt_list),
            "latest_attempt": (
                None if latest_attempt is None else latest_attempt.to_dict()
            ),
            "funnel": (
                {
                    "raw_results": total_results,
                    "normalized": total_results,
                    "deduplicated": candidate_count,
                    "screened": candidate_count,
                    "new_candidates": candidate_count,
                }
                if latest_attempt is None
                else {
                    "raw_results": latest_attempt.raw_result_count,
                    "normalized": latest_attempt.normalized_count,
                    "deduplicated": latest_attempt.deduplicated_count,
                    "screened": latest_attempt.screened_count,
                    "new_candidates": latest_attempt.new_candidate_count,
                }
            ),
            "suggested_queries": list(QueryPlanner.suggest(run.topic)),
            "providers": sorted(
                provider_stats.values(),
                key=lambda item: str(item["provider"]),
            ),
            "corpus_alignment": corpus_alignment,
            "recommendations": self._recommendations(
                issue,
                provider_stats.values(),
                corpus_alignment,
            ),
        }

    @staticmethod
    def _provider_error_category(message: str) -> str:
        lowered = message.lower()
        if "429" in lowered:
            return "rate_limited"
        if "network" in lowered or "unavailable" in lowered:
            return "network_unavailable"
        if "timeout" in lowered:
            return "timeout"
        return "provider_error"

    def _corpus_alignment(self, run: ResearchRun) -> dict[str, object]:
        request = self.runtime.stored_request(run.run_id)
        corpus_path = request.get("corpus_path")
        if not isinstance(corpus_path, str) or not corpus_path:
            return {"status": "unknown", "overlap_terms": []}
        topic_tokens = self._meaningful_tokens(run.topic)
        if not topic_tokens:
            return {"status": "unknown", "overlap_terms": []}
        try:
            records = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
        except Exception:
            return {"status": "unknown", "overlap_terms": []}
        if not isinstance(records, list):
            return {"status": "unknown", "overlap_terms": []}
        corpus_text = " ".join(
            " ".join(
                str(value)
                for value in (
                    item.get("title", ""),
                    item.get("category", ""),
                    item.get("contribution", ""),
                    (
                        " ".join(item.get("tags", []))
                        if isinstance(item.get("tags"), list)
                        else ""
                    ),
                )
            )
            for item in records
            if isinstance(item, Mapping)
        )
        overlap = sorted(topic_tokens & self._meaningful_tokens(corpus_text))
        return {
            "status": "low" if not overlap else "aligned",
            "overlap_terms": overlap[:8],
        }

    @staticmethod
    def _meaningful_tokens(text: str) -> set[str]:
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "for",
            "in",
            "llm",
            "of",
            "on",
            "or",
            "system",
            "systems",
            "the",
            "to",
            "with",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 2 and token not in stopwords
        }

    @staticmethod
    def _recommendations(
        issue: str,
        provider_stats: Iterable[Mapping[str, object]],
        corpus_alignment: Mapping[str, object],
    ) -> list[str]:
        recommendations: list[str] = []
        if issue == "provider_failure":
            recommendations.append("retry_discovery_later")
        if issue == "zero_candidates":
            recommendations.extend(
                [
                    "broaden_topic",
                    "increase_max_results",
                    "try_arxiv_only",
                ]
            )
        if corpus_alignment.get("status") == "low":
            recommendations.append("review_seed_corpus")
        for stats in provider_stats:
            categories = set(stats.get("error_categories") or [])
            if (
                stats.get("last_error_category") == "rate_limited"
                or "rate_limited" in categories
            ):
                recommendations.append("configure_semantic_scholar_key")
            if categories & {"network_unavailable", "timeout"} or stats.get(
                "last_error_category"
            ) in {"network_unavailable", "timeout"}:
                recommendations.append("retry_discovery_later")
        if issue == "zero_candidates":
            recommendations.append("continue_with_seed_corpus")
        return list(dict.fromkeys(recommendations))


__all__ = ["DiscoveryDiagnostics", "RuntimeDiagnostics"]
