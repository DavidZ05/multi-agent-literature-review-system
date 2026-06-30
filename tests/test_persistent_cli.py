import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from src.literature_review.cli import main


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

    def test_no_arguments_preserve_legacy_one_shot_command(self) -> None:
        fake_result = {"status": "accepted", "survey": "outputs/survey.md"}
        with patch("src.literature_review.cli.Orchestrator") as orchestrator:
            orchestrator.return_value.run.return_value = fake_result
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                code = main([])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), fake_result)


if __name__ == "__main__":
    unittest.main()
