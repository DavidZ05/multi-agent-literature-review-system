from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from src.literature_review.activity import (
    ActivityCoordinator,
    RunBusy,
    RunDeletionBusy,
)


RUN_ID = "run_0123456789abcdef0123456789abcdef"
OTHER_RUN_ID = "run_fedcba9876543210fedcba9876543210"


def _hold_resume_until_exit(artifact_root: str, ready: object) -> None:
    coordinator = ActivityCoordinator.for_artifact_root(Path(artifact_root))
    reservation = coordinator.reserve_resume(RUN_ID)
    ready.send(True)  # type: ignore[attr-defined]
    ready.recv()  # type: ignore[attr-defined]
    assert reservation.run_id == RUN_ID
    os._exit(0)


class ActivityCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.artifact_root = Path(self.tmp.name) / "artifacts"
        self.coordinator = ActivityCoordinator.for_artifact_root(
            self.artifact_root
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_coordinators_are_shared_by_resolved_artifact_root(self) -> None:
        alias = self.artifact_root / ".." / "artifacts"

        self.assertIs(
            self.coordinator,
            ActivityCoordinator.for_artifact_root(alias),
        )

    def test_queued_resume_reservation_blocks_deletion_until_released(self) -> None:
        reservation = self.coordinator.reserve_resume(RUN_ID)

        with self.assertRaises(RunBusy) as raised:
            self.coordinator.reserve_deletion(RUN_ID)
        self.assertEqual(raised.exception.run_id, RUN_ID)

        reservation.release()
        deletion = self.coordinator.reserve_deletion(RUN_ID)
        deletion.release()

    def test_deletion_reservation_blocks_new_resume_submission(self) -> None:
        deletion = self.coordinator.reserve_deletion(RUN_ID)

        with self.assertRaises(RunDeletionBusy) as raised:
            self.coordinator.reserve_resume(RUN_ID)
        self.assertEqual(raised.exception.run_id, RUN_ID)

        deletion.release()

    def test_independent_runs_can_hold_resume_reservations_concurrently(self) -> None:
        first = self.coordinator.reserve_resume(RUN_ID)
        second = self.coordinator.reserve_resume(OTHER_RUN_ID)

        second.release()
        first.release()

    def test_second_same_run_resume_is_busy_in_process(self) -> None:
        first = self.coordinator.reserve_resume(RUN_ID)

        try:
            with self.assertRaises(RunBusy) as raised:
                self.coordinator.reserve_resume(RUN_ID)
        finally:
            first.release()

        self.assertEqual(raised.exception.run_id, RUN_ID)

    def test_start_and_deletion_reservations_conflict_both_directions(self) -> None:
        start = self.coordinator.reserve_start()
        with self.assertRaises(RunBusy):
            self.coordinator.reserve_deletion(RUN_ID)
        start.release()

        deletion = self.coordinator.reserve_deletion(RUN_ID)
        with self.assertRaises(RunDeletionBusy):
            self.coordinator.reserve_start()
        deletion.release()

    def test_simultaneous_thread_reservations_have_one_winner(self) -> None:
        barrier = threading.Barrier(3)
        acquired: list[object] = []
        failures: list[BaseException] = []

        def reserve(operation: str) -> None:
            barrier.wait()
            try:
                if operation == "resume":
                    acquired.append(self.coordinator.reserve_resume(RUN_ID))
                else:
                    acquired.append(self.coordinator.reserve_deletion(RUN_ID))
            except BaseException as exc:
                failures.append(exc)

        threads = [
            threading.Thread(target=reserve, args=("resume",)),
            threading.Thread(target=reserve, args=("delete",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(len(acquired), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], (RunBusy, RunDeletionBusy))
        acquired[0].release()  # type: ignore[attr-defined]

    @unittest.skipUnless(os.name == "posix", "requires POSIX advisory locks")
    def test_process_exit_releases_resume_advisory_lock(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_hold_resume_until_exit,
            args=(str(self.artifact_root), child),
        )
        process.start()
        child.close()
        try:
            self.assertTrue(
                parent.poll(5),
                "child did not acquire resume reservation",
            )
            self.assertTrue(parent.recv())
            with self.assertRaises(RunBusy):
                self.coordinator.reserve_deletion(RUN_ID)
            parent.send("exit")
            process.join(timeout=5)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            parent.close()
        self.assertEqual(process.exitcode, 0)
        deletion = self.coordinator.reserve_deletion(RUN_ID)
        deletion.release()

    @unittest.skipUnless(os.name == "posix", "requires POSIX advisory locks")
    def test_second_same_run_resume_is_busy_across_processes(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_hold_resume_until_exit,
            args=(str(self.artifact_root), child),
        )
        process.start()
        child.close()

        try:
            self.assertTrue(
                parent.poll(5),
                "child did not acquire resume reservation",
            )
            self.assertTrue(parent.recv())
            with self.assertRaises(RunBusy):
                self.coordinator.reserve_resume(RUN_ID)
            parent.send("exit")
            process.join(timeout=5)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            parent.close()

        self.assertEqual(process.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
