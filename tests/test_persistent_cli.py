import io
import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import ANY, MagicMock, patch

from src.literature_review.activity import (
    ActivityCoordinator,
    RunBusy,
    RunDeletionBusy,
)
from src.literature_review.cli import main
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench.service import (
    RunDeletionConflictError,
    WorkbenchService,
)
from src.literature_review.workbench.deletion import ArtifactReconciliationReport


class PersistentCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "state" / "workflow.db"
        self.artifact_path = root / "artifacts"
        self.corpus_path = Path(__file__).resolve().parents[1] / "data" / "papers.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *arguments: str) -> tuple[int, object, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "--db",
            str(self.db_path),
            "--artifacts",
            str(self.artifact_path),
            *arguments,
        ]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = int(exc.code)
        output = stdout.getvalue().strip()
        return code, json.loads(output) if output else None, stderr.getvalue()

    def test_start_status_events_and_list_share_persistent_state(self) -> None:
        code, started, stderr = self._run(
            "start",
            "--topic",
            "Memory agents",
            "--corpus",
            str(self.corpus_path),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(started["status"], "completed")
        run_id = started["run_id"]

        code, status, stderr = self._run("status", run_id)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(status, started)

        code, events, stderr = self._run("events", run_id)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(events[0]["event_type"], "run_created")
        self.assertEqual(events[-1]["event_type"], "run_completed")

        code, runs, stderr = self._run("list")
        self.assertEqual(code, 0, stderr)
        self.assertEqual([run["run_id"] for run in runs], [run_id])

    def test_resume_completed_run_is_idempotent(self) -> None:
        _, started, _ = self._run(
            "start",
            "--topic",
            "Memory agents",
            "--corpus",
            str(self.corpus_path),
        )

        code, resumed, stderr = self._run("resume", started["run_id"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(resumed, started)

    def test_cancel_is_persisted_and_terminal(self) -> None:
        _, started, _ = self._run(
            "start",
            "--topic",
            "Memory agents",
            "--corpus",
            str(self.corpus_path),
        )
        from src.literature_review.models import RunStatus
        from src.literature_review.storage import SQLiteWorkflowStore
        from dataclasses import replace
        from src.literature_review.models import utc_now_iso

        store = SQLiteWorkflowStore(self.db_path)
        completed = store.get_run(started["run_id"])
        store.update_run(
            replace(
                completed,
                status=RunStatus.PAUSED,
                updated_at=utc_now_iso(),
            )
        )

        code, cancelled, stderr = self._run("cancel", started["run_id"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(cancelled["status"], "cancelled")
        _, resumed, _ = self._run("resume", started["run_id"])
        self.assertEqual(resumed["status"], "cancelled")

    def test_unknown_run_returns_nonzero_json_error(self) -> None:
        code, output, stderr = self._run(
            "status", "run_0123456789abcdef0123456789abcdef"
        )

        self.assertEqual(code, 2)
        self.assertIsNone(output)
        self.assertIn("run_not_found", stderr)

    def test_runtime_configuration_errors_are_stable_json_errors(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_BASE_URL": "https://api.example.com/v1",
                "AGENT_API_KEY": "secret-key",
            },
            clear=True,
        ):
            code, output, stderr = self._run(
                "start",
                "--topic",
                "Memory agents",
                "--corpus",
                str(self.corpus_path),
            )

        self.assertEqual(code, 2)
        self.assertIsNone(output)
        payload = json.loads(stderr)
        self.assertEqual(payload["error"], "configuration_error")
        self.assertIn("AGENT_MODEL", payload["message"])
        self.assertNotIn("secret-key", stderr)

    def test_delete_uses_custom_storage_and_prints_success_json(self) -> None:
        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        run = replace(
            ResearchRun.create("Delete completed run"),
            status=RunStatus.COMPLETED,
        )
        store.create_run(run)
        artifact = self.artifact_path / "runs" / run.run_id / "result.txt"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("delete me", encoding="utf-8")

        code, output, stderr = self._run("delete", run.run_id)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(output["run_id"], run.run_id)
        self.assertEqual(output["status"], "deleted")
        self.assertTrue(output["artifacts_removed"])
        self.assertFalse(artifact.exists())
        self.assertEqual(store.list_runs(), [])

    def test_delete_not_deletable_is_stable_json_error(self) -> None:
        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        run = replace(
            ResearchRun.create("Active run"),
            status=RunStatus.ACTIVE,
        )
        store.create_run(run)

        code, output, stderr = self._run("delete", run.run_id)

        self.assertEqual(code, 3)
        self.assertIsNone(output)
        self.assertEqual(
            json.loads(stderr),
            {
                "error": "run_not_deletable",
                "run_id": run.run_id,
                "status": "active",
            },
        )
        self.assertEqual(store.get_run(run.run_id), run)

    def test_delete_conflict_is_stable_json_error(self) -> None:
        run_id = "run_0123456789abcdef0123456789abcdef"
        conflict = RunDeletionConflictError(
            run_id,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        )

        with patch.object(
            WorkbenchService,
            "delete_run",
            side_effect=conflict,
        ):
            code, output, stderr = self._run("delete", run_id)

        self.assertEqual(code, 3)
        self.assertIsNone(output)
        self.assertEqual(
            json.loads(stderr),
            {
                "error": "run_deletion_conflict",
                "run_id": run_id,
                "expected_status": "completed",
                "actual_status": "failed",
            },
        )

    def test_activity_conflicts_are_stable_json_errors(self) -> None:
        run_id = "run_0123456789abcdef0123456789abcdef"
        cases = (
            (RunBusy(run_id), "run_busy"),
            (RunDeletionBusy(run_id), "run_deletion_busy"),
        )

        for error, expected_code in cases:
            with self.subTest(error=expected_code):
                with patch.object(
                    WorkbenchService,
                    "delete_run",
                    side_effect=error,
                ):
                    code, output, stderr = self._run("delete", run_id)

                self.assertEqual(code, 3)
                self.assertIsNone(output)
                self.assertEqual(
                    json.loads(stderr),
                    {"error": expected_code, "run_id": run_id},
                )

    def test_resume_reserves_before_store_and_artifact_preflight(self) -> None:
        run_id = "run_0123456789abcdef0123456789abcdef"
        deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_path
        ).reserve_deletion(run_id)

        try:
            with (
                patch.object(
                    SQLiteWorkflowStore,
                    "get_run",
                    side_effect=AssertionError("store preflight must not run"),
                ) as get_run,
                patch(
                    "src.literature_review.storage.LocalArtifactStore.read_json",
                    side_effect=AssertionError("artifact preflight must not run"),
                ) as read_json,
            ):
                code, output, stderr = self._run("resume", run_id)
        finally:
            deletion.release()

        self.assertEqual(code, 3)
        self.assertIsNone(output)
        self.assertEqual(
            json.loads(stderr),
            {"error": "run_deletion_busy", "run_id": run_id},
        )
        get_run.assert_not_called()
        read_json.assert_not_called()

    def test_delete_unknown_run_retains_not_found_behavior(self) -> None:
        run_id = "run_0123456789abcdef0123456789abcdef"

        code, output, stderr = self._run("delete", run_id)

        self.assertEqual(code, 2)
        self.assertIsNone(output)
        self.assertEqual(
            json.loads(stderr),
            {"error": "run_not_found", "run_id": run_id},
        )

    def test_candidate_approval_commands_are_json_and_persistent(self) -> None:
        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        run = ResearchRun.create("Memory agents")
        store.create_run(run)
        store.upsert_candidate(
            run.run_id,
            CandidatePaper(
                candidate_id="cand_cli",
                title="New Agent Memory",
                authors=("A. Author",),
                year=2026,
                venue="arXiv",
                abstract="Memory.",
                doi=None,
                arxiv_id="2601.00001",
                semantic_scholar_id=None,
                source_urls=("https://arxiv.org/abs/2601.00001",),
                open_access_pdf_url=None,
                provenance=("arxiv:2601.00001",),
                recommendation=ScreeningRecommendation.INCLUDE,
                relevance_score=0.9,
                status=CandidateStatus.PENDING,
            ),
        )

        code, candidates, stderr = self._run("candidates", run.run_id)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(candidates[0]["status"], "pending")
        code, decision, stderr = self._run(
            "approve",
            run.run_id,
            "cand_cli",
            "--reason",
            "Core evidence",
            "--category",
            "memory mechanism",
            "--contribution",
            "Introduces a new memory mechanism.",
            "--tags",
            "memory",
            "mechanism",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(decision["status"], "approved")
        _, approved, _ = self._run("candidates", run.run_id, "--status", "approved")
        self.assertEqual([item["candidate_id"] for item in approved], ["cand_cli"])

    def test_resume_refuses_pending_approval_without_failing_run(self) -> None:
        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        run = ResearchRun.create("Memory agents")
        waiting = replace(
            run,
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        store.create_run(waiting)
        store.upsert_candidate(
            waiting.run_id,
            CandidatePaper(
                "cand_waiting",
                "Pending paper",
                ("A. Author",),
                2026,
                "arXiv",
                "Memory",
                None,
                "2601.00002",
                None,
                ("https://arxiv.org/abs/2601.00002",),
                None,
                ("arxiv:2601.00002",),
                ScreeningRecommendation.REVIEW,
                0.5,
                CandidateStatus.PENDING,
            ),
        )

        code, output, stderr = self._run("resume", waiting.run_id)

        self.assertEqual(code, 3)
        self.assertIsNone(output)
        self.assertIn("approval_required", stderr)
        self.assertEqual(
            store.get_run(waiting.run_id).status,
            RunStatus.WAITING,
        )
        deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_path
        ).reserve_deletion(waiting.run_id)
        deletion.release()

    def test_resume_preflight_errors_release_activity_reservation(self) -> None:
        missing_run_id = ResearchRun.create("Missing").run_id

        code, output, stderr = self._run("resume", missing_run_id)

        self.assertEqual(code, 2)
        self.assertIsNone(output)
        self.assertIn("run_not_found", stderr)
        missing_deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_path
        ).reserve_deletion(missing_run_id)
        missing_deletion.release()

        store = SQLiteWorkflowStore(self.db_path)
        run = ResearchRun.create("Missing settings")
        store.create_run(run)
        with self.assertRaises(FileNotFoundError):
            self._run("resume", run.run_id)
        artifact_deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_path
        ).reserve_deletion(run.run_id)
        artifact_deletion.release()

    def test_no_arguments_preserve_legacy_one_shot_command(self) -> None:
        fake_result = {"status": "accepted", "survey": "outputs/survey.md"}
        with patch("src.literature_review.cli.Orchestrator") as orchestrator:
            orchestrator.return_value.run.return_value = fake_result
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                code = main([])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), fake_result)

    def test_ui_dispatches_shared_runtime_paths_and_browser_preference(self) -> None:
        with patch(
            "src.literature_review.cli.run_workbench",
            return_value=0,
        ) as runner:
            code = main(
                [
                    "--db",
                    str(self.db_path),
                    "--artifacts",
                    str(self.artifact_path),
                    "ui",
                    "--host",
                    "localhost",
                    "--port",
                    "8123",
                    "--no-browser",
                ]
            )

        self.assertEqual(code, 0)
        runner.assert_called_once()
        call = runner.call_args
        self.assertEqual(call.args[0].path, self.db_path)
        self.assertEqual(call.args[1], self.artifact_path)
        self.assertEqual(call.kwargs["host"], "localhost")
        self.assertEqual(call.kwargs["port"], 8123)
        self.assertFalse(call.kwargs["open_browser"])
        self.assertEqual(
            call.kwargs["default_corpus_path"],
            Path(__file__).resolve().parents[1]
            / "src"
            / "literature_review"
            / "resources"
            / "papers.json",
        )

    def test_run_workbench_opens_browser_and_closes_runtime_on_interrupt(self) -> None:
        from src.literature_review.cli import run_workbench

        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        manager = MagicMock()
        server = MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch(
                "src.literature_review.cli.WorkflowJobManager",
                return_value=manager,
            ),
            patch(
                "src.literature_review.cli.create_workbench_server",
                return_value=server,
            ) as create_server,
            patch("src.literature_review.cli.webbrowser.open") as open_browser,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            code = run_workbench(
                store,
                self.artifact_path,
                host="127.0.0.1",
                port=8765,
                open_browser=True,
                default_corpus_path=self.corpus_path,
            )

        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:8765/", stdout.getvalue())
        open_browser.assert_called_once_with("http://127.0.0.1:8765/")
        create_server.assert_called_once()
        manager.shutdown.assert_called_once_with(wait=True)
        server.server_close.assert_called_once_with()

    def test_run_workbench_reconciles_stale_and_interrupted_quarantines(
        self,
    ) -> None:
        from src.literature_review.cli import run_workbench

        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        current = replace(
            ResearchRun.create("Preserve rollback quarantine"),
            status=RunStatus.FAILED,
        )
        store.create_run(current)
        stale_run_id = "run_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        pending = self.artifact_path / ".delete-pending"
        interrupted = pending / f"{current.run_id}--delete-{'b' * 32}"
        stale = pending / f"{stale_run_id}--delete-{'c' * 32}"
        interrupted.mkdir(parents=True)
        (interrupted / "result.txt").write_text("restore", encoding="utf-8")
        stale.mkdir()
        manager = MagicMock()
        server = MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch(
                "src.literature_review.cli.WorkflowJobManager",
                return_value=manager,
            ),
            patch(
                "src.literature_review.cli.create_workbench_server",
                return_value=server,
            ) as create_server,
            redirect_stdout(io.StringIO()),
        ):
            code = run_workbench(
                store,
                self.artifact_path,
                host="127.0.0.1",
                port=8765,
                open_browser=False,
                default_corpus_path=self.corpus_path,
            )

        self.assertEqual(code, 0)
        self.assertFalse(interrupted.exists())
        self.assertFalse(stale.exists())
        self.assertEqual(
            (
                self.artifact_path
                / "runs"
                / current.run_id
                / "result.txt"
            ).read_text(encoding="utf-8"),
            "restore",
        )
        service = create_server.call_args.args[0]
        self.assertEqual(service.artifact_root, self.artifact_path.resolve())

    def test_run_workbench_cleanup_failure_warns_without_leaking_details(
        self,
    ) -> None:
        from src.literature_review.cli import run_workbench

        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        manager = MagicMock()
        server = MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt
        secret = "private/path/delete-pending"

        with (
            patch(
                "src.literature_review.cli.WorkflowJobManager",
                return_value=manager,
            ),
            patch(
                "src.literature_review.cli.create_workbench_server",
                return_value=server,
            ),
            patch(
                "src.literature_review.workbench.deletion."
                "ArtifactDeletionManager.reconcile_pending",
                side_effect=OSError(secret),
            ) as cleanup,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            code = run_workbench(
                store,
                self.artifact_path,
                host="127.0.0.1",
                port=8765,
                open_browser=False,
                default_corpus_path=self.corpus_path,
            )

        self.assertEqual(code, 0)
        cleanup.assert_called_once_with(ANY, activity=ANY)
        self.assertTrue(callable(cleanup.call_args.args[0]))
        self.assertEqual(
            stderr.getvalue(),
            "Warning: artifact reconciliation failed; continuing.\n",
        )
        self.assertNotIn(secret, stderr.getvalue())

    def test_run_workbench_warns_with_only_unresolved_count(self) -> None:
        from src.literature_review.cli import run_workbench

        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        manager = MagicMock()
        server = MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch(
                "src.literature_review.cli.WorkflowJobManager",
                return_value=manager,
            ),
            patch(
                "src.literature_review.cli.create_workbench_server",
                return_value=server,
            ),
            patch(
                "src.literature_review.workbench.deletion."
                "ArtifactDeletionManager.reconcile_pending",
                return_value=ArtifactReconciliationReport(unresolved=2),
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            code = run_workbench(
                store,
                self.artifact_path,
                host="127.0.0.1",
                port=8765,
                open_browser=False,
                default_corpus_path=self.corpus_path,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            stderr.getvalue(),
            "Warning: 2 artifact quarantines need manual recovery.\n",
        )

    def test_run_workbench_passes_same_root_coordinator_to_reconciliation(
        self,
    ) -> None:
        from src.literature_review.cli import run_workbench

        store = SQLiteWorkflowStore(self.db_path)
        store.initialize()
        manager = MagicMock()
        server = MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt
        coordinator = MagicMock()
        coordinator.artifact_root = self.artifact_path.resolve()

        with (
            patch(
                "src.literature_review.cli.WorkflowJobManager",
                return_value=manager,
            ),
            patch(
                "src.literature_review.cli.create_workbench_server",
                return_value=server,
            ),
            patch(
                "src.literature_review.cli.ActivityCoordinator."
                "for_artifact_root",
                return_value=coordinator,
            ),
            patch(
                "src.literature_review.workbench.deletion."
                "ArtifactDeletionManager.reconcile_pending",
                return_value=ArtifactReconciliationReport(),
            ) as reconcile,
            redirect_stdout(io.StringIO()),
        ):
            code = run_workbench(
                store,
                self.artifact_path,
                host="127.0.0.1",
                port=8765,
                open_browser=False,
                default_corpus_path=self.corpus_path,
            )

        self.assertEqual(code, 0)
        reconcile.assert_called_once()
        call = reconcile.call_args
        self.assertEqual(call.kwargs, {"activity": coordinator})
        self.assertEqual(len(call.args), 1)
        run_exists = call.args[0]
        self.assertTrue(callable(run_exists))

        live = ResearchRun.create("Live")
        store.create_run(live)
        self.assertTrue(run_exists(live.run_id))
        self.assertFalse(run_exists(ResearchRun.create("Missing").run_id))
        with patch.object(
            store,
            "get_run",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                run_exists(live.run_id)

    def test_ui_rejects_out_of_range_port_before_launch(self) -> None:
        with (
            patch(
                "src.literature_review.cli.run_workbench",
            ) as runner,
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                main(["ui", "--port", "70000", "--no-browser"])

        runner.assert_not_called()

    def test_persistent_commands_check_platform_support_first(self) -> None:
        with patch(
            "src.literature_review.cli.require_supported_platform",
        ) as platform_guard:
            code, output, stderr = self._run("list")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(output, [])
        platform_guard.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
