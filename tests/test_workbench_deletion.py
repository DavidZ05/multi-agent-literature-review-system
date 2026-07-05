from dataclasses import FrozenInstanceError
import multiprocessing
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from src.literature_review.activity import ActivityCoordinator, RunBusy
from src.literature_review.workbench import (
    ArtifactDeletionHandle,
    ArtifactDeletionManager,
    ArtifactReconciliationReport,
)


RUN_ID = "run_0123456789abcdef0123456789abcdef"
OTHER_RUN_ID = "run_fedcba9876543210fedcba9876543210"


def _run_exists(*run_ids: str):
    existing = frozenset(run_ids)
    return existing.__contains__


def _hold_deletion_reservation(
    artifact_root: str,
    run_id: str,
    connection: object,
) -> None:
    reservation = ActivityCoordinator.for_artifact_root(
        Path(artifact_root)
    ).reserve_deletion(run_id)
    connection.send(True)  # type: ignore[attr-defined]
    connection.recv()  # type: ignore[attr-defined]
    reservation.release()


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

    def test_quarantine_treats_source_disappearing_before_replace_as_race(
        self,
    ) -> None:
        source = self.create_run_artifacts()
        original_replace = Path.replace

        def disappear_then_replace(path: Path, target: Path) -> Path:
            if path == source.resolve():
                for child in path.iterdir():
                    child.unlink()
                path.rmdir()
            return original_replace(path, target)

        with patch.object(
            Path,
            "replace",
            autospec=True,
            side_effect=disappear_then_replace,
        ):
            handle = self.manager.quarantine(RUN_ID)

        self.assertIsNone(handle)

    def test_quarantine_does_not_hide_other_replace_errors(self) -> None:
        self.create_run_artifacts()

        with patch.object(
            Path,
            "replace",
            autospec=True,
            side_effect=PermissionError("denied"),
        ):
            with self.assertRaisesRegex(PermissionError, "denied"):
                self.manager.quarantine(RUN_ID)

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

    def test_reconcile_restores_unique_live_run_and_purges_missing_db_run(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        live = pending / f"{RUN_ID}--delete-{'a' * 32}"
        stale = pending / f"{OTHER_RUN_ID}--delete-{'b' * 32}"
        live.mkdir(parents=True)
        stale.mkdir()
        (live / "result.txt").write_text("restore", encoding="utf-8")

        report = self.manager.reconcile_pending(_run_exists(RUN_ID))

        self.assertEqual(
            report,
            ArtifactReconciliationReport(
                purged=1,
                restored=1,
                unresolved=0,
            ),
        )
        self.assertFalse(stale.exists())
        self.assertFalse(live.exists())
        self.assertEqual(
            (self.root / "runs" / RUN_ID / "result.txt").read_text(
                encoding="utf-8"
            ),
            "restore",
        )

    def test_reconcile_preserves_source_conflict_and_multiple_quarantines(
        self,
    ) -> None:
        source = self.create_run_artifacts(RUN_ID)
        pending = self.root / ".delete-pending"
        source_conflict = pending / f"{RUN_ID}--delete-{'a' * 32}"
        first = pending / f"{OTHER_RUN_ID}--delete-{'b' * 32}"
        second = pending / f"{OTHER_RUN_ID}--delete-{'c' * 32}"
        source_conflict.mkdir(parents=True)
        first.mkdir()
        second.mkdir()

        report = self.manager.reconcile_pending(
            _run_exists(RUN_ID, OTHER_RUN_ID)
        )

        self.assertEqual(
            report,
            ArtifactReconciliationReport(
                purged=0,
                restored=0,
                unresolved=3,
            ),
        )
        self.assertTrue(source.is_dir())
        self.assertTrue(source_conflict.is_dir())
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())

    def test_reconcile_does_not_restore_live_run_while_deletion_is_busy(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        quarantine = pending / f"{RUN_ID}--delete-{'a' * 32}"
        quarantine.mkdir(parents=True)
        (quarantine / "result.txt").write_text("keep", encoding="utf-8")
        coordinator = ActivityCoordinator.for_artifact_root(self.root)
        active_deletion = coordinator.reserve_deletion(RUN_ID)

        try:
            report = self.manager.reconcile_pending(
                _run_exists(RUN_ID),
                activity=coordinator,
            )
        finally:
            active_deletion.release()

        self.assertEqual(
            report,
            ArtifactReconciliationReport(unresolved=1),
        )
        self.assertTrue(quarantine.is_dir())
        self.assertFalse((self.root / "runs" / RUN_ID).exists())

    def test_reconcile_does_not_purge_missing_db_run_while_deletion_is_busy(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        quarantine = pending / f"{OTHER_RUN_ID}--delete-{'b' * 32}"
        quarantine.mkdir(parents=True)
        (quarantine / "result.txt").write_text("keep", encoding="utf-8")
        coordinator = ActivityCoordinator.for_artifact_root(self.root)
        active_deletion = coordinator.reserve_deletion(OTHER_RUN_ID)

        try:
            report = self.manager.reconcile_pending(
                _run_exists(),
                activity=coordinator,
            )
        finally:
            active_deletion.release()

        self.assertEqual(
            report,
            ArtifactReconciliationReport(unresolved=1),
        )
        self.assertTrue(quarantine.is_dir())
        self.assertEqual(
            (quarantine / "result.txt").read_text(encoding="utf-8"),
            "keep",
        )

    def test_reconcile_releases_group_reservation_when_mutation_fails(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        quarantine = pending / f"{RUN_ID}--delete-{'a' * 32}"
        quarantine.mkdir(parents=True)
        coordinator = ActivityCoordinator.for_artifact_root(self.root)

        with patch(
            "src.literature_review.workbench.deletion.shutil.rmtree",
            side_effect=OSError("purge failed"),
        ):
            with self.assertRaisesRegex(OSError, "purge failed"):
                self.manager.reconcile_pending(
                    _run_exists(),
                    activity=coordinator,
                )

        reservation = coordinator.reserve_deletion(RUN_ID)
        reservation.release()

    def test_reconcile_revalidates_stale_live_run_view_under_reservation(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        quarantine = pending / f"{RUN_ID}--delete-{'a' * 32}"
        quarantine.mkdir(parents=True)
        startup_view = {RUN_ID}
        database_rows: set[str] = set()
        coordinator = ActivityCoordinator.for_artifact_root(self.root)
        callback_calls: list[str] = []

        def run_exists(run_id: str) -> bool:
            callback_calls.append(run_id)
            with self.assertRaises(RunBusy):
                coordinator.reserve_deletion(run_id)
            return run_id in database_rows

        self.assertIn(RUN_ID, startup_view)
        report = self.manager.reconcile_pending(
            run_exists,
            activity=coordinator,
        )

        self.assertEqual(callback_calls, [RUN_ID])
        self.assertEqual(
            report,
            ArtifactReconciliationReport(purged=1),
        )
        self.assertFalse(quarantine.exists())
        self.assertFalse((self.root / "runs" / RUN_ID).exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX advisory locks")
    def test_reconcile_preserves_quarantine_locked_by_another_process(
        self,
    ) -> None:
        pending = self.root / ".delete-pending"
        quarantine = pending / f"{RUN_ID}--delete-{'a' * 32}"
        quarantine.mkdir(parents=True)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_hold_deletion_reservation,
            args=(str(self.root), RUN_ID, child),
        )
        process.start()
        child.close()

        try:
            self.assertTrue(
                parent.poll(5),
                "child did not acquire deletion reservation",
            )
            self.assertTrue(parent.recv())
            report = self.manager.reconcile_pending(
                _run_exists(RUN_ID),
                activity=ActivityCoordinator.for_artifact_root(self.root),
            )
            parent.send("release")
            process.join(timeout=5)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            parent.close()

        self.assertEqual(process.exitcode, 0)
        self.assertEqual(
            report,
            ArtifactReconciliationReport(unresolved=1),
        )
        self.assertTrue(quarantine.is_dir())
        self.assertFalse((self.root / "runs" / RUN_ID).exists())

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
