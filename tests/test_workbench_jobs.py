from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import threading
import unittest

from src.literature_review import cli
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.runtime import load_resume_settings
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workbench import PendingCandidatesError
from src.literature_review.workbench.jobs import (
    DuplicateResumeJobError,
    StartRunRequest,
    WorkflowJobManager,
)


class ManualExecutor:
    def __init__(self) -> None:
        self.tasks: list[tuple[object, tuple[object, ...]]] = []
        self.shutdown_calls: list[bool] = []

    def submit(self, function: object, *args: object) -> None:
        self.tasks.append((function, args))

    def run_next(self) -> None:
        function, args = self.tasks.pop(0)
        function(*args)  # type: ignore[operator]

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


class FakeEngine:
    def __init__(
        self,
        run: ResearchRun,
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self.run = run
        self.entered = entered
        self.release = release
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def start(self, topic: str, corpus_path: Path) -> ResearchRun:
        self.calls.append(("start", (topic, corpus_path)))
        return self._finish()

    def resume(self, run_id: str) -> ResearchRun:
        self.calls.append(("resume", run_id))
        return self._finish()

    def _finish(self) -> ResearchRun:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait()
        if self.error is not None:
            raise self.error
        return self.run


def pending_candidate() -> CandidatePaper:
    return CandidatePaper(
        candidate_id="cand_pending",
        title="Pending paper",
        authors=("Ada Researcher",),
        year=2026,
        venue="Test",
        abstract="Pending review.",
        doi=None,
        arxiv_id="2601.00001",
        semantic_scholar_id=None,
        source_urls=("https://example.test/pending",),
        open_access_pdf_url=None,
        provenance=("test:pending",),
        recommendation=ScreeningRecommendation.REVIEW,
        relevance_score=0.5,
        status=CandidateStatus.PENDING,
    )


class StartRunRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.corpus_path = Path(self.tmp.name) / "papers.json"
        self.corpus_path.write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalizes_values_and_is_immutable(self) -> None:
        request = StartRunRequest(
            topic="  Memory agents  ",
            corpus_path=self.corpus_path.parent / "." / self.corpus_path.name,
            discovery_enabled=True,
            providers=(" Semantic_Scholar ", "ARXIV", "arxiv"),
            max_results=25,
        )

        self.assertEqual(request.topic, "Memory agents")
        self.assertEqual(request.corpus_path, self.corpus_path.resolve())
        self.assertEqual(request.providers, ("semantic_scholar", "arxiv"))
        with self.assertRaises(FrozenInstanceError):
            request.topic = "Changed"  # type: ignore[misc]

    def test_rejects_invalid_inputs_before_scheduling(self) -> None:
        missing = self.corpus_path.with_name("missing.json")
        cases = (
            ({"topic": " "}, "topic must be nonblank"),
            ({"corpus_path": missing}, "corpus_path must be an existing file"),
            ({"discovery_enabled": True, "providers": ()}, "providers must be nonempty"),
            ({"providers": ("crossref",)}, "unknown provider"),
            ({"max_results": True}, "max_results must be an integer"),
            ({"max_results": 0}, "max_results must be between 1 and 50"),
            ({"max_results": 51}, "max_results must be between 1 and 50"),
        )
        defaults = {
            "topic": "Memory",
            "corpus_path": self.corpus_path,
            "discovery_enabled": False,
            "providers": ("arxiv",),
            "max_results": 10,
        }
        for changes, message in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex((TypeError, ValueError), message):
                    StartRunRequest(**{**defaults, **changes})


class WorkflowJobManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifact_root = root / "artifacts"
        self.corpus_path = root / "papers.json"
        self.corpus_path.write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request(self, **changes: object) -> StartRunRequest:
        values = {
            "topic": "Memory agents",
            "corpus_path": self.corpus_path,
            "discovery_enabled": True,
            "providers": ("arxiv", "semantic_scholar"),
            "max_results": 7,
        }
        return StartRunRequest(**{**values, **changes})

    def test_submit_start_returns_while_engine_is_blocked_and_tracks_lifecycle(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        run = ResearchRun.create("Memory agents")
        engine = FakeEngine(run, entered=entered, release=release)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            max_workers=1,
        )

        accepted = manager.submit_start(self._request())

        self.assertEqual(accepted["status"], "queued")
        self.assertTrue(entered.wait(timeout=2), "worker did not start")
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "running")
        self.assertFalse(release.is_set())
        release.set()
        manager.shutdown()

        completed = manager.get_job(accepted["job_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], run.to_dict())
        self.assertIsNone(completed["error"])
        self.assertEqual(
            engine.calls,
            [("start", ("Memory agents", self.corpus_path.resolve()))],
        )
        json.dumps(accepted)
        json.dumps(completed)

    def test_manual_executor_exposes_queued_to_succeeded_transition(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            executor=executor,
        )

        accepted = manager.submit_start(self._request())

        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "queued")
        executor.run_next()
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "succeeded")
        manager.shutdown(wait=False)
        self.assertEqual(executor.shutdown_calls, [False])

    def test_start_command_is_replay_safe_and_contains_discovery_settings(self) -> None:
        executor = ManualExecutor()
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(
                ResearchRun.create("Memory agents")
            ),
            executor=executor,
        )
        request = self._request(topic="-memory agents")

        accepted = manager.submit_start(request)
        tokens = shlex.split(accepted["equivalent_command"])
        parsed = cli._parser().parse_args(tokens[3:])

        self.assertEqual(parsed.command, "start")
        self.assertEqual(parsed.topic, request.topic)
        self.assertEqual(parsed.corpus, request.corpus_path)
        self.assertTrue(parsed.discover)
        self.assertEqual(tuple(parsed.providers), request.providers)
        self.assertEqual(parsed.max_results, request.max_results)
        self.assertIn(f"--topic={request.topic}", tokens)
        self.assertIn(f"--corpus={request.corpus_path}", tokens)
        self.assertIn(f"--max-results={request.max_results}", tokens)

    def test_failure_is_captured_without_traceback(self) -> None:
        executor = ManualExecutor()
        engine = FakeEngine(
            ResearchRun.create("Memory agents"),
            error=RuntimeError("provider unavailable"),
        )
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            executor=executor,
        )
        accepted = manager.submit_start(self._request())

        executor.run_next()

        failed = manager.get_job(accepted["job_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            failed["error"],
            {"type": "RuntimeError", "message": "provider unavailable"},
        )
        self.assertIsNone(failed["result"])
        self.assertNotIn("traceback", json.dumps(failed).lower())

    def test_duplicate_resume_conflicts_only_while_existing_job_is_active(
        self,
    ) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        artifact_store = LocalArtifactStore(self.artifact_root)
        artifact_store.write_json(
            run.run_id,
            "inputs/research_request.json",
            {"runtime_config": {}},
        )
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            executor=executor,
        )

        first = manager.submit_resume(run.run_id)
        with self.assertRaises(DuplicateResumeJobError) as raised:
            manager.submit_resume(run.run_id)
        self.assertEqual(raised.exception.run_id, run.run_id)
        self.assertEqual(raised.exception.existing_job_id, first["job_id"])

        executor.run_next()
        second = manager.submit_resume(run.run_id)

        self.assertNotEqual(second["job_id"], first["job_id"])
        self.assertEqual(
            shlex.split(second["equivalent_command"])[-2:],
            ["resume", run.run_id],
        )

    def test_resume_rejects_pending_approval_before_scheduling(self) -> None:
        executor = ManualExecutor()
        run = replace(
            ResearchRun.create("Memory agents"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(run)
        self.store.upsert_candidate(run.run_id, pending_candidate())
        builder_calls: list[object] = []
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: builder_calls.append(kwargs),
            executor=executor,
        )

        with self.assertRaises(PendingCandidatesError) as raised:
            manager.submit_resume(run.run_id)

        self.assertEqual(raised.exception.run_id, run.run_id)
        self.assertEqual(raised.exception.pending_count, 1)
        self.assertEqual(executor.tasks, [])
        self.assertEqual(builder_calls, [])

    def test_resume_loads_stored_settings_and_builds_matching_engine(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        LocalArtifactStore(self.artifact_root).write_json(
            run.run_id,
            "inputs/research_request.json",
            {
                "runtime_config": {
                    "discovery_enabled": True,
                    "discovery_providers": ["semantic_scholar"],
                    "discovery_max_results": 23,
                }
            },
        )
        builder_calls: list[tuple[object, Path, dict[str, object]]] = []
        engine = FakeEngine(run)

        def build(
            store: object,
            artifact_root: Path,
            **settings: object,
        ) -> FakeEngine:
            builder_calls.append((store, artifact_root, settings))
            return engine

        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=build,
            executor=executor,
        )

        accepted = manager.submit_resume(run.run_id)
        executor.run_next()

        self.assertEqual(
            builder_calls,
            [
                (
                    self.store,
                    self.artifact_root.resolve(),
                    {
                        "discovery_enabled": True,
                        "providers": ("semantic_scholar",),
                        "max_results": 23,
                    },
                )
            ],
        )
        self.assertEqual(engine.calls, [("resume", run.run_id)])
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "succeeded")

    def test_resume_settings_public_loader_preserves_cli_defaults(self) -> None:
        run = ResearchRun.create("Memory agents")
        artifact_store = LocalArtifactStore(self.artifact_root)
        artifact_store.write_json(
            run.run_id,
            "inputs/research_request.json",
            {"runtime_config": {}},
        )

        self.assertEqual(
            load_resume_settings(artifact_store, run.run_id),
            (False, ("arxiv", "semantic_scholar"), 10),
        )


if __name__ == "__main__":
    unittest.main()
