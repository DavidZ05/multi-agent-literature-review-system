from dataclasses import replace
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.literature_review import cli
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery import ApprovalService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
)
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench import (
    PendingCandidatesError,
    RunDeletionConflictError,
    RunDeletionRollbackError,
    RunNotDeletableError,
    WorkbenchService,
)
from src.literature_review.workbench.deletion import ArtifactDeletionManager
from src.literature_review.workflow import PersistentWorkflowEngine


def candidate(candidate_id: str, status: CandidateStatus) -> CandidatePaper:
    return CandidatePaper(
        candidate_id=candidate_id,
        title=f"Paper {candidate_id}",
        authors=("Ada Researcher",),
        year=2025,
        venue="Test Conference",
        abstract="A test candidate.",
        doi=f"10.1000/{candidate_id}",
        arxiv_id=None,
        semantic_scholar_id=None,
        source_urls=(f"https://example.test/{candidate_id}",),
        open_access_pdf_url=None,
        provenance=(f"test:{candidate_id}",),
        recommendation=ScreeningRecommendation.INCLUDE,
        relevance_score=0.9,
        status=status,
    )


class NoCandidateHydrationStore(SQLiteWorkflowStore):
    def list_candidates(
        self,
        *args: object,
        **kwargs: object,
    ) -> list[CandidatePaper]:
        raise AssertionError("list_runs must not hydrate candidates")


class WorkbenchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.store = SQLiteWorkflowStore(Path(self.tmp.name) / "workflow.db")
        self.store.initialize()
        self.older_run = replace(
            ResearchRun.create("Older topic"),
            created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-01-01T00:00:00+00:00",
        )
        self.newer_run = replace(
            ResearchRun.create("Newer topic"),
            created_at="2025-01-02T00:00:00+00:00",
            updated_at="2025-01-02T00:00:00+00:00",
        )
        self.store.create_run(self.older_run)
        self.store.create_run(self.newer_run)
        self.approved = candidate("cand_alpha", CandidateStatus.APPROVED)
        self.pending = candidate("cand_zulu", CandidateStatus.PENDING)
        self.store.upsert_candidate(self.older_run.run_id, self.pending)
        self.store.upsert_candidate(self.older_run.run_id, self.approved)
        self.service = WorkbenchService(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_runs_is_newest_first_with_complete_candidate_counts(self) -> None:
        service = WorkbenchService(NoCandidateHydrationStore(self.store.path))

        result = service.list_runs()

        self.assertEqual(
            [item["run_id"] for item in result],
            [self.newer_run.run_id, self.older_run.run_id],
        )
        self.assertEqual(
            result[0],
            {
                **self.newer_run.to_dict(),
                "candidate_counts": {
                    "pending": 0,
                    "approved": 0,
                    "rejected": 0,
                    "deferred": 0,
                },
            },
        )
        self.assertEqual(
            result[1]["candidate_counts"],
            {
                "pending": 1,
                "approved": 1,
                "rejected": 0,
                "deferred": 0,
            },
        )

    def test_get_run_detail_returns_json_native_run_activity(self) -> None:
        event = self.store.append_event(
            self.older_run.run_id,
            "screening_completed",
            {"candidate_count": 2},
            WorkflowStage.SCREENING,
        )

        detail = self.service.get_run_detail(self.older_run.run_id)

        self.assertEqual(
            detail,
            {
                "run": self.older_run.to_dict(),
                "candidate_counts": {
                    "pending": 1,
                    "approved": 1,
                    "rejected": 0,
                    "deferred": 0,
                },
                "events": [event.to_dict()],
                "candidates": [
                    self.approved.to_dict(),
                    self.pending.to_dict(),
                ],
                "runtime": {
                    "backend": "deterministic",
                    "api_mode": "single",
                    "model_summary": "deterministic",
                    "model_names": [],
                    "api_enabled_agents": [],
                    "current_executor": "workflow_planner",
                    "safe_error_category": None,
                },
                "discovery_summary": {
                    "enabled": False,
                    "issue": "not_run",
                    "candidate_count": 2,
                    "pending_count": 1,
                    "total_queries": 0,
                    "total_results": 0,
                    "total_failures": 0,
                    "providers": [],
                    "corpus_alignment": {
                        "status": "unknown",
                        "overlap_terms": [],
                    },
                    "recommendations": [],
                },
            },
        )
        json.dumps(detail)

    def test_get_run_detail_summarizes_zero_candidate_discovery(self) -> None:
        run = replace(
            self.newer_run,
            topic="Football",
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
        )
        self.store.update_run(run)
        corpus_path = Path(self.tmp.name) / "memory_papers.json"
        corpus_path.write_text(
            json.dumps(
                [
                    {
                        "citation_key": "park2023generative",
                        "title": "Generative Agents with Memory",
                        "authors": ["Ada Researcher"],
                        "year": 2023,
                        "venue": "Test",
                        "url": "https://example.test/paper",
                        "category": "memory mechanism",
                        "contribution": "Studies memory retrieval in agents.",
                        "evidence": "metadata",
                        "tags": ["memory", "agents"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        artifact_root = Path(self.tmp.name) / "artifacts"
        LocalArtifactStore(artifact_root).write_json(
            run.run_id,
            "inputs/research_request.json",
            {
                "topic": run.topic,
                "corpus_path": str(corpus_path),
                "runtime_config": {},
            },
        )
        self.store.append_event(
            run.run_id,
            "query_started",
            {"provider": "arxiv", "query_id": "query_a"},
            WorkflowStage.DISCOVERING,
        )
        self.store.append_event(
            run.run_id,
            "query_completed",
            {"provider": "arxiv", "query_id": "query_a", "result_count": 0},
            WorkflowStage.DISCOVERING,
        )
        self.store.append_event(
            run.run_id,
            "provider_failed",
            {
                "provider": "semantic_scholar",
                "query_id": "query_s2",
                "error_type": "ProviderRequestError",
                "message": "provider request failed with HTTP 429",
            },
            WorkflowStage.DISCOVERING,
        )

        detail = WorkbenchService(
            self.store,
            artifact_root=artifact_root,
        ).get_run_detail(run.run_id)

        self.assertEqual(
            detail["discovery_summary"],
            {
                "enabled": True,
                "issue": "zero_candidates",
                "candidate_count": 0,
                "pending_count": 0,
                "total_queries": 1,
                "total_results": 0,
                "total_failures": 1,
                "providers": [
                    {
                        "provider": "arxiv",
                        "queries": 1,
                        "completed_queries": 1,
                        "result_count": 0,
                        "failures": 0,
                        "error_categories": [],
                        "last_error_type": None,
                        "last_error_category": None,
                        "last_error_message": None,
                    },
                    {
                        "provider": "semantic_scholar",
                        "queries": 0,
                        "completed_queries": 0,
                        "result_count": 0,
                        "failures": 1,
                        "error_categories": ["rate_limited"],
                        "last_error_type": "ProviderRequestError",
                        "last_error_category": "rate_limited",
                        "last_error_message": "provider request failed with HTTP 429",
                    },
                ],
                "corpus_alignment": {
                    "status": "low",
                    "overlap_terms": [],
                },
                "recommendations": [
                    "broaden_topic",
                    "increase_max_results",
                    "try_arxiv_only",
                    "review_seed_corpus",
                    "configure_semantic_scholar_key",
                    "continue_with_seed_corpus",
                ],
            },
        )

    def test_get_run_detail_adds_sanitized_api_runtime_state(self) -> None:
        api_run = replace(
            self.older_run,
            status=RunStatus.RETRY_WAIT,
            current_stage=WorkflowStage.DRAFTING,
        )
        self.store.update_run(api_run)
        artifact_root = Path(self.tmp.name) / "artifacts"
        runtime_config = AgentRuntimeConfig.from_env(
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_MODE": "single",
                "AGENT_API_BASE_URL": "https://api.example.com/v1",
                "AGENT_API_KEY": "secret-key",
                "AGENT_MODEL": "shared-model",
            }
        ).public_dict()
        LocalArtifactStore(artifact_root).write_json(
            api_run.run_id,
            "inputs/research_request.json",
            {"runtime_config": runtime_config},
        )
        self.store.append_event(
            api_run.run_id,
            "stage_retry_wait",
            {
                "error_type": "RetryableStageError",
                "message": "API provider retryable failure (timeout)",
            },
            WorkflowStage.DRAFTING,
        )

        detail = WorkbenchService(
            self.store,
            artifact_root=artifact_root,
        ).get_run_detail(api_run.run_id)

        self.assertEqual(
            detail["runtime"],
            {
                "backend": "api",
                "api_mode": "single",
                "model_summary": "single_model",
                "model_names": ["shared-model"],
                "api_enabled_agents": [
                    "writer",
                    "domain_expert",
                    "structure_mentor",
                    "review_synthesizer",
                    "polish",
                    "evaluation_reflection",
                ],
                "current_executor": "model_agent_loop",
                "safe_error_category": "retryable_api_failure",
            },
        )
        self.assertNotIn("secret-key", json.dumps(detail))

    def test_list_candidates_preserves_store_order_and_filters_by_status(self) -> None:
        self.assertEqual(
            self.service.list_candidates(self.older_run.run_id),
            [self.approved.to_dict(), self.pending.to_dict()],
        )
        self.assertEqual(
            self.service.list_candidates(
                self.older_run.run_id,
                CandidateStatus.APPROVED,
            ),
            [self.approved.to_dict()],
        )

    def test_approve_candidate_delegates_with_workbench_actor_and_safe_command(
        self,
    ) -> None:
        reason = "Strong evidence; don't execute $(touch /tmp/nope)"
        category = "memory mechanism"
        contribution = "Explains 'reflection' and recall."
        tags = ("memory systems", "reviewer's-choice")

        result = self.service.approve_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
            category,
            contribution,
            tags,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.APPROVED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(
            details,
            {
                "category": category,
                "contribution": contribution,
                "tags": list(tags),
            },
        )
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "approve",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                    f"--category={category}",
                    f"--contribution={contribution}",
                    *(f"--tags={tag}" for tag in tags),
                ]
            ),
        )
        json.dumps(result)

    def test_approve_equivalent_command_replays_dash_and_spaced_values(
        self,
    ) -> None:
        cases = (
            ("-reason", "-category", "-contribution", ("-tag", "-second")),
            (
                "-reason with spaces",
                "-category with spaces",
                "-contribution with spaces",
                ("-tag with spaces", "-second tag"),
            ),
        )
        for reason, category, contribution, tags in cases:
            with self.subTest(reason=reason):
                result = self.service.approve_candidate(
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    reason,
                    category,
                    contribution,
                    tags,
                )
                tokens = shlex.split(result["equivalent_command"])

                self.assertEqual(
                    tokens[:3],
                    ["python3", "-m", "src.memory_review_pipeline"],
                )
                try:
                    parsed = cli._parser().parse_args(tokens[3:])
                except SystemExit as exc:
                    self.fail(f"equivalent command did not parse: {exc}")
                self.assertEqual(parsed.command, "approve")
                self.assertEqual(parsed.run_id, self.older_run.run_id)
                self.assertEqual(parsed.candidate_id, self.pending.candidate_id)
                self.assertEqual(parsed.reason, reason)
                self.assertEqual(parsed.category, category)
                self.assertEqual(parsed.contribution, contribution)
                self.assertEqual(parsed.tags, list(tags))

    def test_approve_parser_preserves_legacy_multi_value_tags(self) -> None:
        parsed = cli._parser().parse_args(
            [
                "approve",
                self.older_run.run_id,
                self.pending.candidate_id,
                "--reason",
                "Useful",
                "--category",
                "Memory",
                "--contribution",
                "Adds evidence",
                "--tags",
                "memory",
                "reflection",
            ]
        )

        self.assertEqual(parsed.tags, ["memory", "reflection"])

    def test_reject_candidate_delegates_with_workbench_actor(self) -> None:
        reason = "Outside scope; quoted as 'irrelevant'"

        result = self.service.reject_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.REJECTED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(details, {})
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "reject",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                ]
            ),
        )
        json.dumps(result)

    def test_defer_candidate_delegates_with_workbench_actor(self) -> None:
        reason = "Read full text before deciding"

        result = self.service.defer_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.DEFERRED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(details, {})
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "defer",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                ]
            ),
        )
        json.dumps(result)

    def test_defer_candidate_rejects_blank_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason is required"):
            self.service.defer_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                " ",
            )

        self.assertEqual(
            self.store.get_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
            ).status,
            CandidateStatus.PENDING,
        )
        self.assertEqual(
            self.store.list_corpus_decisions(self.older_run.run_id),
            [],
        )

    def test_decision_validation_errors_remain_meaningful(self) -> None:
        with self.assertRaisesRegex(ValueError, "category is required"):
            self.service.approve_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                "Useful",
                " ",
                "Contribution",
                ("memory",),
            )
        with self.assertRaisesRegex(ValueError, "reason is required"):
            self.service.reject_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                " ",
            )
        with self.assertRaisesRegex(ValueError, "nonblank tag"):
            self.service.approve_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                "Useful",
                "Memory",
                "Contribution",
                ("memory", " "),
            )

        self.assertEqual(
            self.store.get_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
            ).status,
            CandidateStatus.PENDING,
        )
        self.assertEqual(
            self.store.list_corpus_decisions(self.older_run.run_id),
            [],
        )

    def test_close_discovery_refuses_when_candidates_remain_pending(self) -> None:
        with self.assertRaises(PendingCandidatesError) as raised:
            self.service.close_discovery(self.older_run.run_id)

        self.assertEqual(raised.exception.pending_count, 1)
        self.assertEqual(raised.exception.run_id, self.older_run.run_id)
        self.assertEqual(
            self.store.get_run(self.older_run.run_id),
            self.older_run,
        )

    def test_close_discovery_returns_ready_without_mutating_run(self) -> None:
        ApprovalService(self.store).defer(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason="Review later",
        )

        result = self.service.close_discovery(self.older_run.run_id)

        self.assertEqual(
            result,
            {
                "run_id": self.older_run.run_id,
                "status": "ready_to_resume",
                "equivalent_command": shlex.join(
                    [
                        "python3",
                        "-m",
                        "src.memory_review_pipeline",
                        "close-discovery",
                        self.older_run.run_id,
                    ]
                ),
            },
        )
        self.assertEqual(
            self.store.get_run(self.older_run.run_id),
            self.older_run,
        )
        json.dumps(result)

    def test_cancel_run_delegates_to_engine_and_serializes_result(self) -> None:
        engine = PersistentWorkflowEngine(
            self.store,
            LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
            {},
        )
        calls: list[str] = []

        def cancel(run_id: str) -> ResearchRun:
            calls.append(run_id)
            return engine.cancel(run_id)

        service = WorkbenchService(self.store, cancel=cancel)

        result = service.cancel_run(self.newer_run.run_id)

        cancelled = self.store.get_run(self.newer_run.run_id)
        self.assertEqual(calls, [self.newer_run.run_id])
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        self.assertEqual(result["run"], cancelled.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "cancel",
                    self.newer_run.run_id,
                ]
            ),
        )
        self.assertEqual(
            [
                event.event_type
                for event in self.store.list_events(self.newer_run.run_id)
            ],
            ["run_cancelled"],
        )
        json.dumps(result)

    def test_cancel_run_propagates_unknown_run_from_engine(self) -> None:
        engine = PersistentWorkflowEngine(
            self.store,
            LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
            {},
        )
        calls: list[str] = []

        def cancel(run_id: str) -> ResearchRun:
            calls.append(run_id)
            return engine.cancel(run_id)

        service = WorkbenchService(self.store, cancel=cancel)
        missing_run_id = ResearchRun.create("Missing run").run_id

        with self.assertRaisesRegex(RunNotFoundError, missing_run_id):
            service.cancel_run(missing_run_id)

        self.assertEqual(calls, [missing_run_id])

    def test_delete_run_allows_exactly_terminal_statuses(self) -> None:
        artifact_root = Path(self.tmp.name) / "terminal-artifacts"
        for status in (
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        ):
            with self.subTest(status=status):
                run = replace(ResearchRun.create(status.value), status=status)
                self.store.create_run(run)
                run_dir = artifact_root / "runs" / run.run_id
                run_dir.mkdir(parents=True)
                (run_dir / "result.txt").write_text("delete", encoding="utf-8")

                result = WorkbenchService(
                    self.store,
                    artifact_root=artifact_root,
                ).delete_run(run.run_id)

                with self.assertRaises(RunNotFoundError):
                    self.store.get_run(run.run_id)
                self.assertFalse(run_dir.exists())
                self.assertEqual(result["status"], "deleted")

    def test_delete_run_rejects_nonterminal_statuses_without_mutation(self) -> None:
        artifact_root = Path(self.tmp.name) / "active-artifacts"
        for status in (
            RunStatus.ACTIVE,
            RunStatus.WAITING,
            RunStatus.RETRY_WAIT,
            RunStatus.PAUSED,
        ):
            with self.subTest(status=status):
                run = replace(ResearchRun.create(status.value), status=status)
                self.store.create_run(run)
                run_dir = artifact_root / "runs" / run.run_id
                run_dir.mkdir(parents=True)
                artifact = run_dir / "result.txt"
                artifact.write_text("keep", encoding="utf-8")

                with self.assertRaises(RunNotDeletableError) as raised:
                    WorkbenchService(
                        self.store,
                        artifact_root=artifact_root,
                    ).delete_run(run.run_id)

                self.assertEqual(raised.exception.run_id, run.run_id)
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(self.store.get_run(run.run_id), run)
                self.assertEqual(artifact.read_text(encoding="utf-8"), "keep")

    def test_delete_run_removes_db_artifacts_and_preserves_unrelated_data(
        self,
    ) -> None:
        artifact_root = Path(self.tmp.name) / "artifacts"
        target = replace(
            ResearchRun.create("Delete me"),
            status=RunStatus.COMPLETED,
        )
        other = replace(
            ResearchRun.create("Keep me"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(target)
        self.store.create_run(other)
        target_dir = artifact_root / "runs" / target.run_id
        other_dir = artifact_root / "runs" / other.run_id
        cache_dir = artifact_root / "provider-cache"
        for directory, content in (
            (target_dir, "target"),
            (other_dir, "other"),
            (cache_dir, "cache"),
        ):
            directory.mkdir(parents=True)
            (directory / "data.txt").write_text(content, encoding="utf-8")

        result = WorkbenchService(
            self.store,
            artifact_root=artifact_root,
        ).delete_run(target.run_id)

        self.assertEqual(
            result,
            {
                "run_id": target.run_id,
                "status": "deleted",
                "artifacts_removed": True,
                "cleanup_pending": False,
                "equivalent_command": shlex.join(
                    [
                        "python3",
                        "-m",
                        "src.memory_review_pipeline",
                        f"--db={self.store.path.resolve()}",
                        f"--artifacts={artifact_root.resolve()}",
                        "delete",
                        target.run_id,
                    ]
                ),
            },
        )
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(target.run_id)
        self.assertEqual(self.store.get_run(other.run_id), other)
        self.assertEqual(
            (other_dir / "data.txt").read_text(encoding="utf-8"),
            "other",
        )
        self.assertEqual(
            (cache_dir / "data.txt").read_text(encoding="utf-8"),
            "cache",
        )
        json.dumps(result)

    def test_delete_run_succeeds_when_artifacts_are_missing(self) -> None:
        run = replace(
            ResearchRun.create("No artifacts"),
            status=RunStatus.FAILED,
        )
        self.store.create_run(run)

        result = WorkbenchService(
            self.store,
            artifact_root=Path(self.tmp.name) / "missing-artifacts",
        ).delete_run(run.run_id)

        self.assertFalse(result["artifacts_removed"])
        self.assertFalse(result["cleanup_pending"])
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.run_id)

    def test_delete_run_restores_quarantine_when_db_delete_fails(self) -> None:
        artifact_root = Path(self.tmp.name) / "rollback-artifacts"
        run = replace(
            ResearchRun.create("Rollback"),
            status=RunStatus.CANCELLED,
        )
        self.store.create_run(run)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        artifact = run_dir / "result.txt"
        artifact.write_text("restore", encoding="utf-8")
        service = WorkbenchService(self.store, artifact_root=artifact_root)

        with patch.object(
            self.store,
            "delete_run",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                service.delete_run(run.run_id)

        self.assertEqual(self.store.get_run(run.run_id), run)
        self.assertEqual(artifact.read_text(encoding="utf-8"), "restore")

    def test_delete_run_reports_pending_cleanup_after_os_purge_failure(
        self,
    ) -> None:
        class FailingPurgeHandle:
            def purge(self) -> None:
                raise PermissionError("cannot remove quarantine")

            def restore(self) -> None:
                raise AssertionError("restore must not follow committed deletion")

        class DeletionManager:
            def __init__(self, artifact_root: Path) -> None:
                self.artifact_root = artifact_root.resolve()
                self.handle = FailingPurgeHandle()
                self.quarantined: list[str] = []

            def quarantine(self, run_id: str) -> FailingPurgeHandle:
                self.quarantined.append(run_id)
                return self.handle

        run = replace(
            ResearchRun.create("Pending cleanup"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(run)
        artifact_root = Path(self.tmp.name) / "injected-artifacts"
        manager = DeletionManager(artifact_root)
        service = WorkbenchService(
            self.store,
            artifact_root=artifact_root,
            deletion_manager=manager,
        )

        result = service.delete_run(run.run_id)

        self.assertEqual(manager.quarantined, [run.run_id])
        self.assertTrue(result["artifacts_removed"])
        self.assertTrue(result["cleanup_pending"])
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.run_id)

    def test_delete_run_reports_pending_cleanup_for_non_os_purge_error(
        self,
    ) -> None:
        class FailingPurgeHandle:
            def purge(self) -> None:
                raise ValueError("invalid quarantine metadata")

            def restore(self) -> None:
                raise AssertionError("restore must not follow committed deletion")

        class DeletionManager:
            def __init__(self, artifact_root: Path) -> None:
                self.artifact_root = artifact_root.resolve()

            def quarantine(self, run_id: str) -> FailingPurgeHandle:
                return FailingPurgeHandle()

        run = replace(
            ResearchRun.create("Pending non-OS cleanup"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(run)
        artifact_root = Path(self.tmp.name) / "value-error-artifacts"

        result = WorkbenchService(
            self.store,
            deletion_manager=DeletionManager(artifact_root),
        ).delete_run(run.run_id)

        self.assertTrue(result["artifacts_removed"])
        self.assertTrue(result["cleanup_pending"])
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.run_id)

    def test_delete_run_restores_artifacts_when_status_changes_after_load(
        self,
    ) -> None:
        artifact_root = Path(self.tmp.name) / "race-artifacts"
        run = replace(
            ResearchRun.create("Race"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(run)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        artifact = run_dir / "result.txt"
        artifact.write_text("restore after race", encoding="utf-8")
        original_delete = self.store.delete_run

        def change_status_then_delete(
            run_id: str,
            *,
            expected_status: RunStatus | None = None,
        ) -> None:
            self.store.update_run(replace(run, status=RunStatus.ACTIVE))
            original_delete(run_id, expected_status=expected_status)

        with patch.object(
            self.store,
            "delete_run",
            side_effect=change_status_then_delete,
        ):
            with self.assertRaises(RunNotDeletableError) as raised:
                WorkbenchService(
                    self.store,
                    artifact_root=artifact_root,
                ).delete_run(run.run_id)

        self.assertEqual(raised.exception.status, RunStatus.ACTIVE)
        self.assertEqual(
            self.store.get_run(run.run_id).status,
            RunStatus.ACTIVE,
        )
        self.assertEqual(
            artifact.read_text(encoding="utf-8"),
            "restore after race",
        )

    def test_delete_run_treats_concurrent_missing_row_as_success(self) -> None:
        artifact_root = Path(self.tmp.name) / "duplicate-delete-artifacts"
        run = replace(
            ResearchRun.create("Duplicate delete"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(run)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "result.txt").write_text("delete once", encoding="utf-8")
        original_delete = self.store.delete_run

        def concurrent_delete(
            run_id: str,
            *,
            expected_status: RunStatus | None = None,
        ) -> None:
            original_delete(run_id)
            original_delete(run_id, expected_status=expected_status)

        with patch.object(
            self.store,
            "delete_run",
            side_effect=concurrent_delete,
        ):
            result = WorkbenchService(
                self.store,
                artifact_root=artifact_root,
            ).delete_run(run.run_id)

        self.assertEqual(result["status"], "deleted")
        self.assertTrue(result["artifacts_removed"])
        self.assertFalse(result["cleanup_pending"])
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.run_id)
        self.assertFalse(run_dir.exists())
        self.assertEqual(
            list((artifact_root / ".delete-pending").glob("*")),
            [],
        )

    def test_concurrent_delete_purge_error_reports_cleanup_pending(self) -> None:
        artifact_root = Path(self.tmp.name) / "duplicate-purge-artifacts"
        run = replace(
            ResearchRun.create("Duplicate purge"),
            status=RunStatus.FAILED,
        )
        self.store.create_run(run)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "result.txt").write_text("pending", encoding="utf-8")
        original_delete = self.store.delete_run

        def concurrent_delete(
            run_id: str,
            *,
            expected_status: RunStatus | None = None,
        ) -> None:
            original_delete(run_id)
            original_delete(run_id, expected_status=expected_status)

        with (
            patch.object(
                self.store,
                "delete_run",
                side_effect=concurrent_delete,
            ),
            patch(
                "src.literature_review.workbench.deletion."
                "ArtifactDeletionHandle.purge",
                side_effect=ValueError("purge failed"),
            ),
        ):
            result = WorkbenchService(
                self.store,
                artifact_root=artifact_root,
            ).delete_run(run.run_id)

        self.assertTrue(result["cleanup_pending"])
        self.assertFalse(run_dir.exists())
        self.assertEqual(
            len(list((artifact_root / ".delete-pending").glob("*"))),
            1,
        )

    def test_delete_run_uses_conflict_for_deletable_status_mismatch(self) -> None:
        artifact_root = Path(self.tmp.name) / "terminal-conflict-artifacts"
        run = replace(
            ResearchRun.create("Terminal conflict"),
            status=RunStatus.COMPLETED,
        )
        self.store.create_run(run)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        artifact = run_dir / "result.txt"
        artifact.write_text("restore conflict", encoding="utf-8")
        original_delete = self.store.delete_run

        def change_status_then_delete(
            run_id: str,
            *,
            expected_status: RunStatus | None = None,
        ) -> None:
            self.store.update_run(replace(run, status=RunStatus.FAILED))
            original_delete(run_id, expected_status=expected_status)

        with patch.object(
            self.store,
            "delete_run",
            side_effect=change_status_then_delete,
        ):
            with self.assertRaises(RunDeletionConflictError) as raised:
                WorkbenchService(
                    self.store,
                    artifact_root=artifact_root,
                ).delete_run(run.run_id)

        self.assertEqual(raised.exception.run_id, run.run_id)
        self.assertEqual(
            raised.exception.expected_status,
            RunStatus.COMPLETED,
        )
        self.assertEqual(raised.exception.actual_status, RunStatus.FAILED)
        self.assertEqual(
            artifact.read_text(encoding="utf-8"),
            "restore conflict",
        )
        self.assertEqual(
            self.store.get_run(run.run_id).status,
            RunStatus.FAILED,
        )

    def test_delete_run_preserves_delete_and_restore_errors(self) -> None:
        run = replace(
            ResearchRun.create("Rollback failure"),
            status=RunStatus.FAILED,
        )
        self.store.create_run(run)
        delete_error = RuntimeError("database failed")
        artifact_root = Path(self.tmp.name) / "rollback-failure-artifacts"
        manager = ArtifactDeletionManager(artifact_root)
        run_dir = artifact_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "result.txt").write_text("quarantine", encoding="utf-8")
        service = WorkbenchService(
            self.store,
            deletion_manager=manager,
        )

        def fail_delete(
            run_id: str,
            *,
            expected_status: RunStatus | None = None,
        ) -> None:
            run_dir.mkdir(parents=True)
            raise delete_error

        with patch.object(
            self.store,
            "delete_run",
            side_effect=fail_delete,
        ):
            with self.assertRaises(RunDeletionRollbackError) as raised:
                service.delete_run(run.run_id)

        self.assertIs(raised.exception.delete_error, delete_error)
        self.assertIsInstance(raised.exception.restore_error, FileExistsError)
        self.assertIs(raised.exception.__cause__, delete_error)
        self.assertEqual(self.store.get_run(run.run_id), run)
        quarantines = list(
            (artifact_root / ".delete-pending").glob(
                f"{run.run_id}--delete-*"
            )
        )
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(
            (quarantines[0] / "result.txt").read_text(encoding="utf-8"),
            "quarantine",
        )

    def test_injected_deletion_manager_is_artifact_root_source_of_truth(
        self,
    ) -> None:
        manager_root = Path(self.tmp.name) / "manager root"
        manager = ArtifactDeletionManager(manager_root)
        run = replace(
            ResearchRun.create("Manager root"),
            status=RunStatus.CANCELLED,
        )
        self.store.create_run(run)
        run_dir = manager_root / "runs" / run.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "result.txt").write_text("delete", encoding="utf-8")

        result = WorkbenchService(
            self.store,
            deletion_manager=manager,
        ).delete_run(run.run_id)

        self.assertFalse(run_dir.exists())
        self.assertEqual(
            shlex.split(result["equivalent_command"])[4],
            f"--artifacts={manager_root.resolve()}",
        )

        with self.assertRaisesRegex(ValueError, "artifact root"):
            WorkbenchService(
                self.store,
                artifact_root=Path(self.tmp.name) / "different-root",
                deletion_manager=manager,
            )

    def test_delete_run_command_resolves_and_quotes_custom_paths(self) -> None:
        root = Path(self.tmp.name) / "path with spaces"
        store = SQLiteWorkflowStore(root / "custom workflow.db")
        store.initialize()
        run = replace(
            ResearchRun.create("Quoted command"),
            status=RunStatus.COMPLETED,
        )
        store.create_run(run)
        artifact_root = root / "custom artifacts"

        result = WorkbenchService(
            store,
            artifact_root=artifact_root,
        ).delete_run(run.run_id)

        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    f"--db={store.path.resolve()}",
                    f"--artifacts={artifact_root.resolve()}",
                    "delete",
                    run.run_id,
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
