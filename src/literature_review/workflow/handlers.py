from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import inspect
import json
from pathlib import Path
import re
from typing import Any, Protocol

from src.literature_review.api import APIClientError
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery.approval import ApprovalService
from src.literature_review.discovery.service import (
    AllProvidersFailedError,
    DiscoveryService,
)
from src.literature_review.corpus import load_papers
from src.literature_review.documents import (
    DocumentAcquirer,
    DocumentStatus,
    EvidenceIndexer,
    PDFParser,
)
from src.literature_review.models import CandidateStatus
from src.literature_review.models import WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.plugins import AgentFactory, build_agent_factory
from src.literature_review.workflow.engine import (
    RetryableStageError,
    StageWaitingError,
    StageContext,
    StageResult,
)
from src.literature_review.verification import (
    ClaimExtractor,
    ClaimVerifier,
    VerificationStatus,
    active_evidence_decisions,
)


class OrchestratorRunner(Protocol):
    def run(self) -> dict[str, Any]: ...


OrchestratorFactory = Callable[..., OrchestratorRunner]


class QualityGateRejectedError(RuntimeError):
    """Raised when review iterations end without an accepted draft."""


class PlanningHandler:
    def __init__(
        self,
        *,
        discovery_enabled: bool = False,
        full_text_enabled: bool = False,
    ) -> None:
        self.discovery_enabled = discovery_enabled
        self.full_text_enabled = full_text_enabled

    def __call__(self, context: StageContext) -> StageResult:
        request = {
            "topic": context.run.topic,
            "corpus_path": str(context.corpus_path.resolve()),
            "runtime_config": dict(context.runtime_config),
        }
        return StageResult(
            next_stage=(
                WorkflowStage.DISCOVERING
                if self.discovery_enabled
                else (
                    WorkflowStage.ACQUIRING_DOCUMENTS
                    if self.full_text_enabled
                    else WorkflowStage.DRAFTING
                )
            ),
            output_artifacts={"inputs/research_request.json": request},
        )


class DiscoveryHandler:
    def __init__(self, service: DiscoveryService) -> None:
        self.service = service

    def __call__(self, context: StageContext) -> StageResult:
        try:
            outcome = self.service.run(
                context.run,
                context.artifact_store,
                context.workflow_store,
                cancellation_check=context.is_cancelled,
            )
        except AllProvidersFailedError as exc:
            raise RetryableStageError(str(exc)) from exc
        except Exception:
            context.workflow_store.fail_active_discovery_attempts(context.run.run_id)
            raise
        return StageResult(
            next_stage=WorkflowStage.SCREENING,
            output_artifacts=outcome.output_artifacts,
        )


class ScreeningHandler:
    def __call__(self, context: StageContext) -> StageResult:
        candidates = context.workflow_store.list_candidates(
            context.run.run_id,
            status=CandidateStatus.PENDING,
        )
        if not candidates:
            return StageResult(
                next_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
                output_artifacts={
                    "discovery/screening_summary.json": {
                        "pending_candidate_count": 0,
                        "candidate_ids": [],
                        "review_required": True,
                        "reason": "zero_candidate_discovery",
                    }
                },
                waiting_reason="discovery produced no candidate papers",
            )
        return StageResult(
            next_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            output_artifacts={
                "discovery/screening_summary.json": {
                    "pending_candidate_count": len(candidates),
                    "candidate_ids": [
                        candidate.candidate_id for candidate in candidates
                    ],
                    "review_required": True,
                    "reason": "candidate_corpus_approval",
                }
            },
            waiting_reason="candidate corpus approval required",
        )


class ApprovalGateHandler:
    def __init__(
        self,
        approval_service: ApprovalService,
        *,
        full_text_enabled: bool = False,
    ) -> None:
        self.approval_service = approval_service
        self.full_text_enabled = full_text_enabled

    def __call__(self, context: StageContext) -> StageResult:
        pending = context.workflow_store.list_candidates(
            context.run.run_id,
            status=CandidateStatus.PENDING,
        )
        if pending:
            raise ValueError(f"{len(pending)} candidate decisions are still pending")
        records = self.approval_service.build_approved_corpus(
            context.run.run_id,
            context.corpus_path,
        )
        return StageResult(
            next_stage=(
                WorkflowStage.ACQUIRING_DOCUMENTS
                if self.full_text_enabled
                else WorkflowStage.DRAFTING
            ),
            output_artifacts={
                "discovery/approved_corpus.json": records,
            },
        )


class DocumentAcquisitionHandler:
    def __init__(self, acquirer: DocumentAcquirer | None = None) -> None:
        self.acquirer = acquirer or DocumentAcquirer()

    def __call__(self, context: StageContext) -> StageResult:
        corpus_path = _materialize_corpus(context)
        papers = load_papers(corpus_path)
        outputs: dict[str, Any] = {}
        manifest = []
        for paper in papers:
            if context.is_cancelled():
                break
            result = self.acquirer.acquire(
                context.run.run_id,
                paper,
                context.artifact_store,
            )
            context.workflow_store.put_document(result.document)
            manifest.append(result.document.to_dict())
            if result.downloaded and result.document.relative_path:
                outputs[result.document.relative_path] = context.artifact_store.read_bytes(
                    context.run.run_id,
                    result.document.relative_path,
                )
        outputs["evidence/document_manifest.json"] = {
            "document_count": len(manifest),
            "acquired_count": sum(
                item["status"] == DocumentStatus.ACQUIRED.value for item in manifest
            ),
            "documents": manifest,
        }
        return StageResult(
            next_stage=WorkflowStage.INDEXING_EVIDENCE,
            output_artifacts=outputs,
        )


class EvidenceIndexingHandler:
    def __init__(
        self,
        parser: PDFParser | None = None,
        indexer: EvidenceIndexer | None = None,
    ) -> None:
        self.parser = parser or PDFParser()
        self.indexer = indexer or EvidenceIndexer()

    def __call__(self, context: StageContext) -> StageResult:
        outputs: dict[str, Any] = {}
        summaries = []
        for document in context.workflow_store.list_documents(context.run.run_id):
            if context.is_cancelled():
                break
            if document.status != DocumentStatus.ACQUIRED or not document.relative_path:
                summaries.append(document.to_dict())
                continue
            try:
                parsed = self.parser.parse(
                    document,
                    context.artifact_store.path_for(
                        context.run.run_id,
                        document.relative_path,
                    ),
                )
                chunks = self.indexer.build(parsed)
                context.workflow_store.put_document(parsed.document)
                context.workflow_store.replace_evidence_chunks(
                    context.run.run_id,
                    parsed.document.document_id,
                    chunks,
                )
                outputs[
                    f"evidence/parsed/{parsed.document.citation_key}.json"
                ] = parsed.to_dict()
                summaries.append(
                    {
                        **parsed.document.to_dict(),
                        "chunk_count": len(chunks),
                        "quality_warnings": list(parsed.quality_warnings),
                    }
                )
            except Exception as exc:
                failed = replace(
                    document,
                    status=DocumentStatus.FAILED,
                    error_code=f"parse_failed:{type(exc).__name__}",
                )
                context.workflow_store.put_document(failed)
                summaries.append(failed.to_dict())
        all_chunks = context.workflow_store.list_evidence_chunks(context.run.run_id)
        outputs["evidence/index_manifest.json"] = {
            "document_count": len(summaries),
            "chunk_count": len(all_chunks),
            "documents": summaries,
            "chunks": [chunk.to_dict() for chunk in all_chunks],
        }
        return StageResult(
            next_stage=WorkflowStage.DRAFTING,
            output_artifacts=outputs,
        )


class DraftingHandler:
    _JSON_ARTIFACTS = (
        "search_report.json",
        "review_report.json",
        "final_verification.json",
        "evaluation_report.json",
        "revision_log.json",
    )
    _TEXT_ARTIFACTS = ("survey.md", "reflection_log.md")

    def __init__(
        self,
        runtime_config: AgentRuntimeConfig | None = None,
        *,
        api_client: Any | None = None,
        orchestrator_factory: OrchestratorFactory = Orchestrator,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.api_client = api_client
        self.orchestrator_factory = orchestrator_factory
        self.agent_factory = agent_factory
        self.claim_verification_enabled = False

    def enable_claim_verification(self) -> DraftingHandler:
        self.claim_verification_enabled = True
        return self

    def __call__(self, context: StageContext) -> StageResult:
        attempt_id = _next_agent_attempt(context)
        attempt_path = f"agent_runs/{attempt_id}"
        output_dir = context.artifact_store.path_for(context.run.run_id, attempt_path)
        output_dir.mkdir(parents=True, exist_ok=False)
        context.artifact_store.write_json(
            context.run.run_id,
            f"{attempt_path}/manifest.json",
            {
                "attempt_id": attempt_id,
                "status": "running",
                "workflow_stage": WorkflowStage.DRAFTING.value,
            },
        )

        def record_agent_event(stage: str, payload: dict[str, Any]) -> None:
            context.workflow_store.append_event(
                context.run.run_id,
                "agent_stage_completed",
                {**payload, "attempt_id": attempt_id, "agent_stage": stage},
                WorkflowStage.DRAFTING,
            )

        try:
            corpus_path = context.corpus_path
            approved_path = "discovery/approved_corpus.json"
            if context.artifact_store.exists(context.run.run_id, approved_path):
                corpus_path = output_dir / "inputs" / "approved_corpus.json"
                corpus_path.parent.mkdir(parents=True, exist_ok=True)
                corpus_path.write_text(
                    context.artifact_store.read_text(context.run.run_id, approved_path),
                    encoding="utf-8",
                )
            kwargs: dict[str, Any] = {
                "corpus_path": corpus_path,
                "output_dir": output_dir,
                "runtime_config": self.runtime_config,
                "run_id": context.run.run_id,
            }
            feedback_path = "evidence/revision_feedback.json"
            if context.artifact_store.exists(context.run.run_id, feedback_path):
                kwargs["initial_review_feedback"] = context.artifact_store.read_json(
                    context.run.run_id,
                    feedback_path,
                )
            if self.api_client is not None:
                kwargs["api_client"] = self.api_client
            if self.agent_factory is not None:
                kwargs["agent_factory"] = self.agent_factory
            if _accepts_keyword(self.orchestrator_factory, "event_callback"):
                kwargs["event_callback"] = record_agent_event
            if self.claim_verification_enabled and _accepts_keyword(
                self.orchestrator_factory,
                "defer_evaluation",
            ):
                kwargs["defer_evaluation"] = True
            orchestrator = self.orchestrator_factory(**kwargs)
            orchestrator_result = orchestrator.run()
        except BaseException as exc:
            context.artifact_store.write_json(
                context.run.run_id,
                f"{attempt_path}/manifest.json",
                {
                    "attempt_id": attempt_id,
                    "status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                    "workflow_stage": WorkflowStage.DRAFTING.value,
                    "error_type": type(exc).__name__,
                },
            )
            if isinstance(exc, APIClientError):
                if exc.retryable:
                    raise RetryableStageError(
                        _api_error_message(exc, retryable=True)
                    ) from exc
                raise RuntimeError(_api_error_message(exc, retryable=False)) from exc
            raise

        try:
            artifacts: dict[str, Any] = {}
            json_artifacts = self._JSON_ARTIFACTS
            text_artifacts = self._TEXT_ARTIFACTS
            if self.claim_verification_enabled:
                json_artifacts = tuple(
                    filename
                    for filename in json_artifacts
                    if filename != "evaluation_report.json"
                )
                text_artifacts = tuple(
                    filename
                    for filename in text_artifacts
                    if filename != "reflection_log.md"
                )
            for filename in json_artifacts:
                artifacts[f"final/{filename}"] = json.loads(
                    (output_dir / filename).read_text(encoding="utf-8")
                )
            for filename in text_artifacts:
                artifacts[f"final/{filename}"] = (output_dir / filename).read_text(
                    encoding="utf-8"
                )
        except BaseException as exc:
            context.artifact_store.write_json(
                context.run.run_id,
                f"{attempt_path}/manifest.json",
                {
                    "attempt_id": attempt_id,
                    "status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                    "workflow_stage": WorkflowStage.DRAFTING.value,
                    "error_type": type(exc).__name__,
                },
            )
            raise

        if orchestrator_result.get("status") != "accepted":
            context.artifact_store.write_json(
                context.run.run_id,
                f"{attempt_path}/manifest.json",
                {
                    "attempt_id": attempt_id,
                    "status": "quality_rejected",
                    "workflow_stage": WorkflowStage.DRAFTING.value,
                },
            )
            for relative_path, content in artifacts.items():
                diagnostic_path = relative_path.replace(
                    "final/",
                    "quality_gate/",
                    1,
                )
                if isinstance(content, str):
                    context.artifact_store.write_text(
                        context.run.run_id,
                        diagnostic_path,
                        content,
                    )
                else:
                    context.artifact_store.write_json(
                        context.run.run_id,
                        diagnostic_path,
                        content,
                    )
            raise QualityGateRejectedError(
                "orchestrator review quality gate was not accepted"
            )

        context.artifact_store.write_json(
            context.run.run_id,
            f"{attempt_path}/manifest.json",
            {
                "attempt_id": attempt_id,
                "status": "completed",
                "workflow_stage": WorkflowStage.DRAFTING.value,
            },
        )

        return StageResult(
            next_stage=(
                WorkflowStage.CLAIM_VERIFICATION
                if self.claim_verification_enabled
                else WorkflowStage.COMPLETED
            ),
            output_artifacts=artifacts,
        )


def _next_agent_attempt(context: StageContext) -> str:
    run_root = context.artifact_store.path_for(context.run.run_id, "agent_runs")
    existing = []
    if run_root.is_dir():
        for child in run_root.iterdir():
            match = re.fullmatch(r"attempt_(\d{3,})", child.name)
            if child.is_dir() and match:
                existing.append(int(match.group(1)))
    return f"attempt_{max(existing, default=0) + 1:03d}"


def _accepts_keyword(factory: OrchestratorFactory, name: str) -> bool:
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


class ClaimVerificationHandler:
    def __init__(
        self,
        extractor: ClaimExtractor | None = None,
        verifier: ClaimVerifier | None = None,
    ) -> None:
        self.extractor = extractor or ClaimExtractor()
        self.verifier = verifier or ClaimVerifier()

    def __call__(self, context: StageContext) -> StageResult:
        survey = context.artifact_store.read_text(
            context.run.run_id,
            "final/survey.md",
        )
        prior_claims = context.workflow_store.list_claims(context.run.run_id)
        latest_version = max(
            (claim.draft_version for claim in prior_claims),
            default=0,
        )
        candidate_version = max(1, latest_version)
        candidate_claims = self.extractor.extract(
            context.run.run_id,
            survey,
            draft_version=candidate_version,
        )
        latest_claims = tuple(
            claim
            for claim in prior_claims
            if claim.draft_version == latest_version
        )
        if latest_claims and _claim_content_signature(
            latest_claims
        ) == _claim_content_signature(candidate_claims):
            draft_version = latest_version
            claims = latest_claims
            claims_are_reused = True
        else:
            draft_version = latest_version + 1
            claims_are_reused = False
            claims = (
                candidate_claims
                if draft_version == candidate_version
                else self.extractor.extract(
                    context.run.run_id,
                    survey,
                    draft_version=draft_version,
                )
            )
        documents = tuple(
            context.workflow_store.list_documents(context.run.run_id)
        )
        chunks = tuple(
            context.workflow_store.list_evidence_chunks(context.run.run_id)
        )
        verifications = self.verifier.verify(claims, documents, chunks)
        if not claims_are_reused:
            context.workflow_store.replace_claims(
                context.run.run_id,
                draft_version,
                claims,
            )
        context.workflow_store.put_claim_verifications(verifications)
        report = self.verifier.report(claims, verifications)
        feedback = self.verifier.feedback(claims, verifications)
        return StageResult(
            next_stage=(
                WorkflowStage.EVALUATING
                if report["accepted"]
                else WorkflowStage.AWAITING_EVIDENCE_REVIEW
            ),
            output_artifacts={
                "evidence/claim_verification.json": report,
                "evidence/latest_feedback.json": feedback,
            },
            waiting_reason=(
                None
                if report["accepted"]
                else "claim-level evidence review required"
            ),
        )


class EvidenceReviewGateHandler:
    def __call__(self, context: StageContext) -> StageResult:
        claims = context.workflow_store.list_claims(context.run.run_id)
        latest_version = max(
            (claim.draft_version for claim in claims),
            default=0,
        )
        latest_claim_ids = {
            claim.claim_id for claim in claims if claim.draft_version == latest_version
        }
        verifications = [
            item
            for item in context.workflow_store.list_claim_verifications(
                context.run.run_id
            )
            if item.claim_id in latest_claim_ids
        ]
        blocking = [item for item in verifications if item.blocking]
        decisions = context.workflow_store.list_evidence_review_decisions(
            context.run.run_id
        )
        decisions_by_claim = active_evidence_decisions(verifications, decisions)
        unresolved = [
            item for item in blocking if item.claim_id not in decisions_by_claim
        ]
        if unresolved:
            raise StageWaitingError(
                f"{len({item.claim_id for item in unresolved})} claim decisions remain"
            )
        invalid_accepts = [
            item
            for item in blocking
            if decisions_by_claim[item.claim_id].action == "accept_risk"
            and item.status != VerificationStatus.FULL_TEXT_UNAVAILABLE
        ]
        if invalid_accepts:
            raise ValueError(
                "risk acceptance is allowed only when cited full text is unavailable"
            )
        require_revision = any(
            decisions_by_claim[item.claim_id].action == "require_revision"
            for item in blocking
        )
        if require_revision:
            feedback = context.artifact_store.read_json(
                context.run.run_id,
                "evidence/latest_feedback.json",
            )
            revision_decisions = [
                decision
                for decision in decisions_by_claim.values()
                if decision.action == "require_revision"
                and decision.claim_id in latest_claim_ids
            ]
            feedback = {
                **feedback,
                "revision_request_ids": sorted(
                    decision.decision_id for decision in revision_decisions
                ),
                "source_draft_version": latest_version,
            }
            return StageResult(
                next_stage=WorkflowStage.DRAFTING,
                output_artifacts={"evidence/revision_feedback.json": feedback},
            )
        return StageResult(
            next_stage=WorkflowStage.EVALUATING,
            output_artifacts={
                "evidence/final_review.json": {
                    "status": (
                        "accepted_with_documented_risk"
                        if blocking
                        else "accepted_after_document_refresh"
                    ),
                    "decisions": [
                        decision.to_dict() for decision in decisions_by_claim.values()
                    ],
                    "decision_history": [
                        decision.to_dict() for decision in decisions
                    ],
                }
            },
        )


class EvaluationHandler:
    def __init__(
        self,
        runtime_config: AgentRuntimeConfig | None = None,
        *,
        api_client: Any | None = None,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.api_client = api_client
        self.agent_factory = agent_factory or build_agent_factory()

    def __call__(self, context: StageContext) -> StageResult:
        evaluator = self.agent_factory.create(
            "evaluation_reflection",
            self.runtime_config,
            self.api_client,
        )
        search_report = context.artifact_store.read_json(
            context.run.run_id,
            "final/search_report.json",
        )
        review_report = context.artifact_store.read_json(
            context.run.run_id,
            "final/review_report.json",
        )
        final_verification = context.artifact_store.read_json(
            context.run.run_id,
            "final/final_verification.json",
        )
        revision_artifact = context.artifact_store.read_json(
            context.run.run_id,
            "final/revision_log.json",
        )
        revision_log = revision_artifact.get("iterations", [])
        if not isinstance(revision_log, list):
            raise TypeError("revision log iterations must be a list")
        evidence_context = _evaluation_evidence_context(context)
        evaluate = evaluator.evaluate
        try:
            if _accepts_keyword(evaluate, "evidence_context"):
                report = evaluate(
                    search_report,
                    review_report,
                    final_verification,
                    revision_log,
                    evidence_context=evidence_context,
                )
            else:
                report = evaluate(
                    search_report,
                    review_report,
                    final_verification,
                    revision_log,
                )
            if not isinstance(report, dict):
                raise TypeError("evaluation agent must return an object")
            report = {
                **report,
                "evaluation_scope": "post_evidence",
                "evidence_status": evidence_context["status"],
                "claim_verification": evidence_context,
            }
            reflection = evaluator.to_markdown(report)
        except APIClientError as exc:
            if exc.retryable:
                raise RetryableStageError(
                    _api_error_message(exc, retryable=True)
                ) from exc
            raise RuntimeError(_api_error_message(exc, retryable=False)) from exc
        return StageResult(
            next_stage=WorkflowStage.COMPLETED,
            output_artifacts={
                "final/evaluation_report.json": report,
                "final/reflection_log.md": reflection,
            },
        )


def _evaluation_evidence_context(context: StageContext) -> dict[str, Any]:
    claim_report = context.artifact_store.read_json(
        context.run.run_id,
        "evidence/claim_verification.json",
    )
    final_review = None
    if context.artifact_store.exists(context.run.run_id, "evidence/final_review.json"):
        final_review = context.artifact_store.read_json(
            context.run.run_id,
            "evidence/final_review.json",
        )
    status = "accepted" if claim_report.get("accepted") else "unresolved"
    if isinstance(final_review, dict) and isinstance(final_review.get("status"), str):
        status = final_review["status"]
    return {
        "status": status,
        "claim_verification": claim_report,
        "human_review": final_review,
    }


def _claim_content_signature(claims: tuple[Any, ...]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            claim.text,
            claim.claim_type.value,
            claim.citation_keys,
            claim.section,
            claim.paragraph_index,
            claim.sentence_index,
            claim.requires_citation,
        )
        for claim in claims
    )


def _materialize_corpus(context: StageContext) -> Path:
    approved_path = "discovery/approved_corpus.json"
    if not context.artifact_store.exists(context.run.run_id, approved_path):
        return context.corpus_path
    return context.artifact_store.path_for(context.run.run_id, approved_path)


def _api_error_message(exc: APIClientError, *, retryable: bool) -> str:
    label = "retryable" if retryable else "permanent"
    status = f", status={exc.status}" if exc.status is not None else ""
    return f"API provider {label} failure ({exc.code}{status})"


__all__ = [
    "ApprovalGateHandler",
    "ClaimVerificationHandler",
    "DocumentAcquisitionHandler",
    "DiscoveryHandler",
    "DraftingHandler",
    "EvidenceIndexingHandler",
    "EvidenceReviewGateHandler",
    "EvaluationHandler",
    "OrchestratorFactory",
    "OrchestratorRunner",
    "PlanningHandler",
    "QualityGateRejectedError",
    "ScreeningHandler",
]
