from dataclasses import FrozenInstanceError
from pathlib import Path
import re
import tempfile
import unittest

from src.literature_review.workbench import (
    ArtifactDeletionHandle,
    ArtifactDeletionManager,
)


RUN_ID = "run_0123456789abcdef0123456789abcdef"
OTHER_RUN_ID = "run_fedcba9876543210fedcba9876543210"


class ArtifactDeletionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "artifacts"
        self.manager = ArtifactDeletionManager(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_run_artifacts(self, run_id: str = RUN_ID) -> Path:
        run_path = self.root / "runs" / run_id
        run_path.mkdir(parents=True)
        (run_path / "result.txt").write_text("evidence", encoding="utf-8")
        return run_path

    def test_constructor_rejects_regular_file_artifact_root(self) -> None:
        artifact_file = Path(self.tmp.name) / "artifact-file"
        artifact_file.write_text("keep", encoding="utf-8")

        with self.assertRaises(ValueError):
            ArtifactDeletionManager(artifact_file)

        self.assertEqual(artifact_file.read_text(encoding="utf-8"), "keep")

    def test_quarantine_atomically_moves_existing_run_to_unique_pending_path(
        self,
    ) -> None:
        source = self.create_run_artifacts()

        first = self.manager.quarantine(RUN_ID)

        self.assertIsInstance(first, ArtifactDeletionHandle)
        assert first is not None
        self.assertEqual(first.run_id, RUN_ID)
        self.assertEqual(first.source_path, source.resolve())
        self.assertFalse(source.exists())
        self.assertTrue(first.quarantine_path.is_dir())
        self.assertEqual(
            (first.quarantine_path / "result.txt").read_text(encoding="utf-8"),
            "evidence",
        )
        self.assertEqual(
            first.quarantine_path.parent,
            self.manager.artifact_root / ".delete-pending",
        )
        self.assertRegex(
            first.quarantine_path.name,
            rf"^{re.escape(RUN_ID)}--delete-[0-9a-f]{{32}}$",
        )

        first.restore()
        second = self.manager.quarantine(RUN_ID)

        assert second is not None
        self.assertNotEqual(first.quarantine_path, second.quarantine_path)

    def test_quarantine_returns_none_when_run_artifacts_are_missing(self) -> None:
        self.assertIsNone(self.manager.quarantine(RUN_ID))

    def test_quarantine_rejects_invalid_and_traversal_run_ids(self) -> None:
        invalid_ids = (
            "",
            "run_0123",
            "RUN_0123456789abcdef0123456789abcdef",
            "run_0123456789abcdef0123456789abcdeg",
            "../run_0123456789abcdef0123456789abcdef",
            f"{RUN_ID}/../../outside",
        )

        for run_id in invalid_ids:
            with self.subTest(run_id=run_id):
                with self.assertRaises(ValueError):
                    self.manager.quarantine(run_id)

    def test_handle_is_immutable_and_restore_moves_quarantine_back(self) -> None:
        source = self.create_run_artifacts()
        handle = self.manager.quarantine(RUN_ID)
        assert handle is not None

        with self.assertRaises(FrozenInstanceError):
            handle.run_id = "run_ffffffffffffffffffffffffffffffff"

        handle.restore()

        self.assertTrue(source.is_dir())
        self.assertFalse(handle.quarantine_path.exists())
        self.assertEqual(
            (source / "result.txt").read_text(encoding="utf-8"),
            "evidence",
        )

    def test_restore_refuses_to_replace_a_recreated_source(self) -> None:
        source = self.create_run_artifacts()
        handle = self.manager.quarantine(RUN_ID)
        assert handle is not None
        source.mkdir(parents=True)
        (source / "new.txt").write_text("new", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            handle.restore()

        self.assertTrue(handle.quarantine_path.is_dir())
        self.assertEqual((source / "new.txt").read_text(encoding="utf-8"), "new")

    def test_purge_removes_only_the_handles_quarantine_directory(self) -> None:
        self.create_run_artifacts()
        first = self.manager.quarantine(RUN_ID)
        assert first is not None
        first.restore()
        second = self.manager.quarantine(RUN_ID)
        assert second is not None

        first.quarantine_path.mkdir()
        (first.quarantine_path / "keep.txt").write_text("keep", encoding="utf-8")
        second.purge()

        self.assertTrue(first.quarantine_path.is_dir())
        self.assertFalse(second.quarantine_path.exists())

    def test_cleanup_pending_removes_only_recognized_directories(self) -> None:
        pending = self.root / ".delete-pending"
        recognized = pending / f"{RUN_ID}--delete-{'a' * 32}"
        unrelated_dir = pending / "manual-backup"
        recognized_file = pending / f"{RUN_ID}--delete-{'b' * 32}"
        unrelated_file = pending / "notes.txt"
        recognized.mkdir(parents=True)
        unrelated_dir.mkdir()
        recognized_file.write_text("keep", encoding="utf-8")
        unrelated_file.write_text("keep", encoding="utf-8")

        removed = self.manager.cleanup_pending()

        self.assertEqual(removed, 1)
        self.assertFalse(recognized.exists())
        self.assertTrue(unrelated_dir.is_dir())
        self.assertTrue(recognized_file.is_file())
        self.assertTrue(unrelated_file.is_file())

    def test_cleanup_pending_preserves_quarantines_for_excluded_runs(self) -> None:
        pending = self.root / ".delete-pending"
        excluded = pending / f"{RUN_ID}--delete-{'a' * 32}"
        removable = pending / f"{OTHER_RUN_ID}--delete-{'b' * 32}"
        excluded.mkdir(parents=True)
        removable.mkdir()
        (excluded / "result.txt").write_text("keep", encoding="utf-8")

        removed = self.manager.cleanup_pending(exclude_run_ids={RUN_ID})

        self.assertEqual(removed, 1)
        self.assertTrue(excluded.is_dir())
        self.assertEqual(
            (excluded / "result.txt").read_text(encoding="utf-8"),
            "keep",
        )
        self.assertFalse(removable.exists())

    def test_mutations_reject_paths_that_resolve_outside_artifact_root(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside_run = outside / RUN_ID
        outside_run.mkdir(parents=True)
        (self.root / "runs").parent.mkdir(parents=True)
        (self.root / "runs").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ValueError):
            self.manager.quarantine(RUN_ID)

        self.assertTrue(outside_run.is_dir())

    def test_quarantine_rejects_in_root_runs_parent_symlink(self) -> None:
        actual_runs = self.root / "actual-runs"
        target = actual_runs / RUN_ID
        target.mkdir(parents=True)
        (target / "result.txt").write_text("keep", encoding="utf-8")
        (self.root / "runs").symlink_to(
            actual_runs,
            target_is_directory=True,
        )

        with self.assertRaises(ValueError):
            self.manager.quarantine(RUN_ID)

        self.assertTrue(target.is_dir())
        self.assertEqual(
            (target / "result.txt").read_text(encoding="utf-8"),
            "keep",
        )
        self.assertFalse((self.root / ".delete-pending").exists())

    def test_quarantine_rejects_regular_file_as_runs_parent(self) -> None:
        self.root.mkdir()
        runs = self.root / "runs"
        runs.write_text("keep", encoding="utf-8")

        try:
            self.manager.quarantine(RUN_ID)
        except Exception as exc:
            error: Exception | None = exc
        else:
            error = None

        self.assertIs(type(error), ValueError)
        self.assertEqual(runs.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.root / ".delete-pending").exists())

    def test_quarantine_rejects_regular_file_as_pending_parent(self) -> None:
        source = self.create_run_artifacts()
        pending = self.root / ".delete-pending"
        pending.write_text("keep", encoding="utf-8")

        try:
            self.manager.quarantine(RUN_ID)
        except Exception as exc:
            error: Exception | None = exc
        else:
            error = None

        self.assertIs(type(error), ValueError)
        self.assertTrue(source.is_dir())
        self.assertEqual(
            (source / "result.txt").read_text(encoding="utf-8"),
            "evidence",
        )
        self.assertEqual(pending.read_text(encoding="utf-8"), "keep")

    def test_cleanup_rejects_in_root_pending_parent_symlink(self) -> None:
        actual_pending = self.root / "actual-pending"
        recognized = actual_pending / f"{RUN_ID}--delete-{'d' * 32}"
        recognized.mkdir(parents=True)
        (recognized / "result.txt").write_text("keep", encoding="utf-8")
        (self.root / ".delete-pending").symlink_to(
            actual_pending,
            target_is_directory=True,
        )

        with self.assertRaises(ValueError):
            self.manager.cleanup_pending()

        self.assertTrue(recognized.is_dir())
        self.assertEqual(
            (recognized / "result.txt").read_text(encoding="utf-8"),
            "keep",
        )

    def test_cleanup_leaves_recognized_symlink_to_outside_untouched(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        pending = self.root / ".delete-pending"
        pending.mkdir(parents=True)
        link = pending / f"{RUN_ID}--delete-{'c' * 32}"
        link.symlink_to(outside, target_is_directory=True)

        removed = self.manager.cleanup_pending()

        self.assertEqual(removed, 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(outside.is_dir())


if __name__ == "__main__":
    unittest.main()
