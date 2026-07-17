from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
from pathlib import Path
import re
import shlex

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.discovery import ApprovalService, QueryPlanner
from src.literature_review.documents.service import DocumentImportService
from src.literature_review.exporting import export_audit_bundle
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ResearchRun,
    RunStatus,
    WorkflowStage,
)
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    RunStatusMismatchError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench.deletion import ArtifactDeletionManager
from src.literature_review.verification import (
    EvidenceReviewDecision,
    VerificationStatus,
    active_evidence_decisions,
)


class PendingCandidatesError(RuntimeError):
    def __init__(self, run_id: str, pending_count: int) -> None:
        self.run_id = run_id
        self.pending_count = pending_count
        super().__init__(
            f"cannot close discovery while {pending_count} candidates remain pending"
        )


class RunNotDeletableError(RuntimeError):
    def __init__(self, run_id: str, status: RunStatus) -> None:
        self.run_id = run_id
        self.status = status
        super().__init__(f"run {run_id} cannot be deleted while {status.value}")


class RunDeletionRollbackError(RuntimeError):
    def __init__(
        self,
        run_id: str,
        delete_error: Exception,
        restore_error: Exception,
    ) -> None:
        self.run_id = run_id
        self.delete_error = delete_error
        self.restore_error = restore_error
        super().__init__(
            f"failed to delete run {run_id} and restore its artifacts"
        )


class RunDeletionConflictError(RuntimeError):
    def __init__(
        self,
        run_id: str,
        expected_status: RunStatus,
        actual_status: RunStatus,
    ) -> None:
        self.run_id = run_id
        self.expected_status = expected_status
        self.actual_status = actual_status
        super().__init__(
            f"run {run_id} changed from {expected_status.value} "
            f"to {actual_status.value} during deletion"
        )


class WorkbenchService:
    _COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")
    _DELETABLE_STATUSES = frozenset(
        {
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }
    )
    _MODEL_BACKED_AGENT_IDS = (
        "writer",
        "domain_expert",
        "structure_mentor",
        "review_synthesizer",
        "polish",
        "evaluation_reflection",
    )

    def __init__(
        self,
        store: SQLiteWorkflowStore,
        *,
        cancel: Callable[[str], ResearchRun] | None = None,
        artifact_root: Path | None = None,
        deletion_manager: ArtifactDeletionManager | None = None,
    ) -> None:
        self.store = store
        self.approval_service = ApprovalService(store)
        self._cancel = cancel
        if deletion_manager is not None:
            manager_root = Path(deletion_manager.artifact_root).expanduser().resolve()
            if (
                artifact_root is not None
                and Path(artifact_root).expanduser().resolve() != manager_root
            ):
                raise ValueError(
                    "artifact root must match the deletion manager artifact root"
                )
            self.artifact_root = manager_root
            self._deletion_manager = deletion_manager
        else:
            configured_root = (
                Path(".review-workflow/artifacts")
                if artifact_root is None
                else Path(artifact_root)
            )
            self.artifact_root = configured_root.expanduser().resolve()
            self._deletion_manager = ArtifactDeletionManager(self.artifact_root)
        self._activity = ActivityCoordinator.for_artifact_root(self.artifact_root)

    def list_runs(self) -> list[dict[str, object]]:
        candidate_counts = self.store.list_candidate_counts_by_run()
        result: list[dict[str, object]] = []
        for run in self.store.list_runs():
            serialized: dict[str, object] = run.to_dict()
            serialized["candidate_counts"] = self._serialize_candidate_counts(
                candidate_counts.get(run.run_id, {})
            )
            result.append(serialized)
        return result

    def get_run_detail(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        candidates = self.store.list_candidates(run_id)
        events = self.store.list_events(run_id)
        attempts = self.store.list_discovery_attempts(run_id)
        detail: dict[str, object] = {
            "run": run.to_dict(),
            "candidate_counts": self._candidate_counts(candidates),
            "events": [event.to_dict() for event in events],
            "discovery_attempts": [attempt.to_dict() for attempt in attempts],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "runtime": self._runtime_state(run, events),
            "discovery_summary": self._discovery_summary(
                run,
                candidates,
                events,
                attempts,
            ),
        }
        evidence = self._evidence_detail(run_id)
        outputs = self._output_detail(run_id)
        if evidence["enabled"]:
            detail["evidence"] = evidence
        if outputs["survey_available"]:
            detail["outputs"] = outputs
        return detail

    def decide_evidence(
        self,
        run_id: str,
        claim_id: str,
        action: str,
        reason: str,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("decision reason must be nonblank")
        with self._activity.resume_execution(run_id):
            run = self.store.get_run(run_id)
            if (
                run.status != RunStatus.WAITING
                or run.current_stage != WorkflowStage.AWAITING_EVIDENCE_REVIEW
            ):
                raise ValueError(
                    "evidence decisions require the evidence review gate"
                )
            blocking = self.store.list_claim_verifications(
                run_id,
                claim_id=claim_id,
                blocking_only=True,
            )
            if not blocking:
                raise ValueError("claim has no blocking verification result")
            if action == "accept_risk" and any(
                item.status != VerificationStatus.FULL_TEXT_UNAVAILABLE
                for item in blocking
            ):
                raise ValueError(
                    "risk acceptance requires unavailable full text"
                )
            decision = EvidenceReviewDecision.create(
                run_id,
                claim_id,
                action,
                reason.strip(),
                "human-workbench",
                verification_fingerprints=tuple(
                    item.fingerprint for item in blocking
                ),
            )
            self.store.put_evidence_review_decision(decision)
        return {
            "decision": decision.to_dict(),
            "evidence": self._evidence_detail(run_id),
            "equivalent_command": self._equivalent_command(
                "evidence-decide",
                run_id,
                claim_id,
                f"--action={action}",
                f"--reason={reason.strip()}",
            ),
        }

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        pdf_path: str,
    ) -> dict[str, object]:
        document = DocumentImportService(
            self.store,
            LocalArtifactStore(self.artifact_root),
        ).import_pdf(run_id, citation_key, Path(pdf_path))
        return {
            "document": document.to_dict(),
            "evidence": self._evidence_detail(run_id),
            "equivalent_command": self._equivalent_command(
                f"--db={self.store.path.expanduser().resolve()}",
                f"--artifacts={self.artifact_root}",
                "import-pdf",
                run_id,
                citation_key,
                str(Path(pdf_path).expanduser().resolve()),
            ),
        }

    def export_run(self, run_id: str, *, include_pdfs: bool = True) -> dict[str, object]:
        output_path = (
            self.artifact_root
            / "runs"
            / run_id
            / "exports"
            / f"{run_id}-audit.zip"
        )
        result = export_audit_bundle(
            self.store,
            LocalArtifactStore(self.artifact_root),
            run_id,
            output_path,
            include_pdfs=include_pdfs,
        )
        result["equivalent_command"] = self._equivalent_command(
            f"--db={self.store.path.expanduser().resolve()}",
            f"--artifacts={self.artifact_root}",
            "export",
            run_id,
            f"--output={output_path}",
            *(() if include_pdfs else ("--no-pdfs",)),
        )
        return result

    def list_candidates(
        self,
        run_id: str,
        status: CandidateStatus | None = None,
    ) -> list[dict[str, object]]:
        return [
            candidate.to_dict()
            for candidate in self.store.list_candidates(run_id, status=status)
        ]

    def approve_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
        category: str,
        contribution: str,
        tags: Iterable[str],
    ) -> dict[str, object]:
        tag_values = tuple(tags)
        with self._activity.resume_execution(run_id):
            decision = self.approval_service.approve(
                run_id,
                candidate_id,
                reason=reason,
                category=category,
                contribution=contribution,
                tags=tag_values,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            self._equivalent_command(
                "approve",
                run_id,
                candidate_id,
                f"--reason={reason}",
                f"--category={category}",
                f"--contribution={contribution}",
                *(f"--tags={tag}" for tag in tag_values),
            ),
        )

    def reject_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        with self._activity.resume_execution(run_id):
            decision = self.approval_service.reject(
                run_id,
                candidate_id,
                reason=reason,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            self._equivalent_command(
                "reject",
                run_id,
                candidate_id,
                f"--reason={reason}",
            ),
        )

    def defer_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        with self._activity.resume_execution(run_id):
            decision = self.approval_service.defer(
                run_id,
                candidate_id,
                reason=reason,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            self._equivalent_command(
                "defer",
                run_id,
                candidate_id,
                f"--reason={reason}",
            ),
        )

    def close_discovery(self, run_id: str) -> dict[str, object]:
        with self._activity.resume_execution(run_id):
            pending_count = len(
                self.store.list_candidates(
                    run_id,
                    status=CandidateStatus.PENDING,
                )
            )
            if pending_count:
                raise PendingCandidatesError(run_id, pending_count)
        return {
            "run_id": run_id,
            "status": "ready_to_resume",
            "equivalent_command": self._equivalent_command(
                "close-discovery",
                run_id,
            ),
        }

    def cancel_run(self, run_id: str) -> dict[str, object]:
        if self._cancel is None:
            raise RuntimeError("run cancellation is not configured")
        run = self._cancel(run_id)
        return {
            "run": run.to_dict(),
            "equivalent_command": self._equivalent_command("cancel", run_id),
        }

    def delete_run(self, run_id: str) -> dict[str, object]:
        with self._activity.reserve_deletion(run_id):
            return self._delete_run(run_id)

    def _delete_run(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run.status not in self._DELETABLE_STATUSES:
            raise RunNotDeletableError(run_id, run.status)

        handle = self._deletion_manager.quarantine(run_id)
        try:
            self.store.delete_run(run_id, expected_status=run.status)
        except RunNotFoundError:
            pass
        except Exception as delete_error:
            if handle is not None:
                try:
                    handle.restore()
                except Exception as restore_error:
                    raise RunDeletionRollbackError(
                        run_id,
                        delete_error,
                        restore_error,
                    ) from delete_error
            if isinstance(delete_error, RunStatusMismatchError):
                if delete_error.actual_status in self._DELETABLE_STATUSES:
                    raise RunDeletionConflictError(
                        run_id,
                        delete_error.expected_status,
                        delete_error.actual_status,
                    ) from delete_error
                raise RunNotDeletableError(
                    run_id,
                    delete_error.actual_status,
                ) from delete_error
            raise

        cleanup_pending = False
        if handle is not None:
            try:
                handle.purge()
            except Exception:
                cleanup_pending = True

        return {
            "run_id": run_id,
            "status": "deleted",
            "artifacts_removed": handle is not None,
            "cleanup_pending": cleanup_pending,
            "equivalent_command": self._equivalent_delete_command(run_id),
        }

    def _decision_payload(
        self,
        run_id: str,
        candidate_id: str,
        decision: CorpusDecision,
        equivalent_command: str,
    ) -> dict[str, object]:
        return {
            "candidate": self.store.get_candidate(run_id, candidate_id).to_dict(),
            "decision": decision.to_dict(),
            "equivalent_command": equivalent_command,
        }

    def _evidence_detail(self, run_id: str) -> dict[str, object]:
        documents = self.store.list_documents(run_id)
        all_claims = self.store.list_claims(run_id)
        latest_version = max(
            (claim.draft_version for claim in all_claims),
            default=0,
        )
        claims = [
            claim for claim in all_claims if claim.draft_version == latest_version
        ]
        verifications = self.store.list_claim_verifications(run_id)
        decisions = self.store.list_evidence_review_decisions(run_id)
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.store.list_evidence_chunks(run_id)
        }
        verifications_by_claim: dict[str, list[dict[str, object]]] = {}
        for verification in verifications:
            serialized = verification.to_dict()
            serialized["evidence"] = [
                {
                    **chunks_by_id[chunk_id].to_dict(),
                    "text": chunks_by_id[chunk_id].text[:1200],
                }
                for chunk_id in verification.evidence_chunk_ids
                if chunk_id in chunks_by_id
            ]
            verifications_by_claim.setdefault(verification.claim_id, []).append(
                serialized
            )
        active_decisions = active_evidence_decisions(verifications, decisions)
        decisions_by_claim = {
            claim_id: decision.to_dict()
            for claim_id, decision in active_decisions.items()
        }
        decision_history_by_claim: dict[str, list[dict[str, object]]] = {}
        for decision in decisions:
            decision_history_by_claim.setdefault(decision.claim_id, []).append(
                decision.to_dict()
            )
        claim_rows = []
        for claim in claims:
            results = verifications_by_claim.get(claim.claim_id, [])
            claim_rows.append(
                {
                    **claim.to_dict(),
                    "verifications": results,
                    "blocking": any(bool(item["blocking"]) for item in results),
                    "decision": decisions_by_claim.get(claim.claim_id),
                    "decision_history": decision_history_by_claim.get(
                        claim.claim_id,
                        [],
                    ),
                }
            )
        return {
            "enabled": bool(documents or claims),
            "document_count": len(documents),
            "parsed_document_count": sum(
                item.status.value in {"parsed", "low_quality"} for item in documents
            ),
            "claim_count": len(claims),
            "draft_version": latest_version,
            "blocking_claim_count": sum(row["blocking"] for row in claim_rows),
            "documents": [item.to_dict() for item in documents],
            "claims": claim_rows,
        }

    def _output_detail(self, run_id: str) -> dict[str, object]:
        artifacts = LocalArtifactStore(self.artifact_root)
        survey_path = "final/survey.md"
        available = artifacts.exists(run_id, survey_path)
        survey = artifacts.read_text(run_id, survey_path) if available else ""
        return {
            "survey_available": available,
            "survey_markdown": survey,
        }

    @classmethod
    def _equivalent_command(cls, *arguments: str) -> str:
        return shlex.join([*cls._COMMAND_PREFIX, *arguments])

    def _equivalent_delete_command(self, run_id: str) -> str:
        return self._equivalent_command(
            f"--db={self.store.path.expanduser().resolve()}",
            f"--artifacts={self.artifact_root}",
            "delete",
            run_id,
        )

    def _runtime_state(
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

        api_enabled_agents = []
        model_names = []
        for agent_id in self._MODEL_BACKED_AGENT_IDS:
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

    def _stored_runtime_config(self, run_id: str) -> dict[str, object]:
        artifact_store = LocalArtifactStore(self.artifact_root)
        try:
            request = artifact_store.read_json(
                run_id,
                "inputs/research_request.json",
            )
        except Exception:
            return {}
        if not isinstance(request, dict):
            return {}
        config = request.get("runtime_config", {})
        return config if isinstance(config, dict) else {}

    def _stored_request(self, run_id: str) -> dict[str, object]:
        artifact_store = LocalArtifactStore(self.artifact_root)
        try:
            request = artifact_store.read_json(
                run_id,
                "inputs/research_request.json",
            )
        except Exception:
            return {}
        return request if isinstance(request, dict) else {}

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
        agent_loop_stages = {
            "drafting",
            "reviewing",
            "revising",
            "polishing",
            "final_verification",
        }
        if stage in agent_loop_stages:
            if backend == "api":
                return "model_agent_loop"
            return "deterministic_agent_loop"
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
            if event_type in {
                "discovery_retry_completed",
                "run_completed",
            }:
                return None
        return None

    def _discovery_summary(
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
            if isinstance(payload, Mapping):
                provider = str(payload.get("provider", "")).strip()
            else:
                provider = ""
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
            1
            for candidate in candidate_list
            if candidate.status == CandidateStatus.PENDING
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
                latest_attempt, "status", None
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
                None
                if latest_attempt is None
                else latest_attempt.to_dict()  # type: ignore[attr-defined]
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
            "recommendations": self._discovery_recommendations(
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
        request = self._stored_request(run.run_id)
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
        corpus_tokens = self._meaningful_tokens(corpus_text)
        overlap = sorted(topic_tokens & corpus_tokens)
        status = "low" if not overlap else "aligned"
        return {
            "status": status,
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
    def _discovery_recommendations(
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
        deduped: list[str] = []
        for recommendation in recommendations:
            if recommendation not in deduped:
                deduped.append(recommendation)
        return deduped

    @staticmethod
    def _candidate_counts(
        candidates: Iterable[CandidatePaper],
    ) -> dict[str, int]:
        counts = {status: 0 for status in CandidateStatus}
        for candidate in candidates:
            counts[candidate.status] += 1
        return WorkbenchService._serialize_candidate_counts(counts)

    @staticmethod
    def _serialize_candidate_counts(
        counts: Mapping[CandidateStatus, int],
    ) -> dict[str, int]:
        return {status.value: counts.get(status, 0) for status in CandidateStatus}


__all__ = [
    "PendingCandidatesError",
    "RunDeletionConflictError",
    "RunDeletionRollbackError",
    "RunNotDeletableError",
    "WorkbenchService",
]
