import io
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

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
            code = main(argv)
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
        self.assertEqual(call.kwargs["default_corpus_path"], self.corpus_path)

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


if __name__ == "__main__":
    unittest.main()
