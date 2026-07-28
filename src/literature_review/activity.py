from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import errno
import hashlib
from pathlib import Path
import threading
from typing import Iterator
import weakref

try:
    import fcntl
except ImportError:  # pragma: no cover - isolated portability guard
    fcntl = None  # type: ignore[assignment]


class RunBusy(RuntimeError):
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        super().__init__(
            "workflow activity is in progress"
            if run_id is None
            else f"run {run_id} has workflow activity in progress"
        )


class RunDeletionBusy(RuntimeError):
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        super().__init__(
            "artifact deletion is in progress"
            if run_id is None
            else f"run {run_id} is reserved for deletion"
        )


class UnsupportedPlatformError(RuntimeError):
    """Raised when persistent workflow locking is unavailable."""


class WorkbenchAlreadyRunningError(RuntimeError):
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        super().__init__(
            f"another Workbench is already using database {self.database_path}"
        )


def require_supported_platform() -> None:
    if fcntl is None:
        raise UnsupportedPlatformError(
            "Persistent workflows and the local workbench require POSIX file "
            "locks. Supported platforms are macOS and Linux. Windows support "
            "is planned for a future release."
        )


class _AdvisoryLock:
    def __init__(self, path: Path, *, shared: bool) -> None:
        if fcntl is None:
            raise RuntimeError("workflow activity locks require POSIX fcntl support")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a+b")
        operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(self._handle.fileno(), operation | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise BlockingIOError from exc
            raise

    def release(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle is None:
            return
        if handle.closed:
            return
        assert fcntl is not None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __del__(self) -> None:
        self.release()


class WorkbenchInstanceGuard:
    """Own an exclusive process lock for one Workbench database."""

    def __init__(self, database_path: Path) -> None:
        database_path = Path(database_path).expanduser().resolve()
        lock_path = database_path.parent / f".{database_path.name}.workbench.lock"
        try:
            self._lock = _AdvisoryLock(lock_path, shared=False)
        except BlockingIOError as exc:
            raise WorkbenchAlreadyRunningError(database_path) from exc
        self.database_path = database_path

    def release(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        self._lock = None
        lock.release()

    def __enter__(self) -> WorkbenchInstanceGuard:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class ActivityReservation:
    def __init__(
        self,
        coordinator: ActivityCoordinator,
        kind: str,
        run_id: str | None,
        locks: tuple[_AdvisoryLock, ...],
    ) -> None:
        self._coordinator = coordinator
        self.kind = kind
        self.run_id = run_id
        self._locks = locks
        self._released = False

    @contextmanager
    def activate(self) -> Iterator[None]:
        if self._released:
            raise RuntimeError("activity reservation has been released")
        token = _ACTIVE_RESERVATION.set(self)
        try:
            yield
        finally:
            _ACTIVE_RESERVATION.reset(token)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._coordinator._release(self)

    def __enter__(self) -> ActivityReservation:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


_ACTIVE_RESERVATION: ContextVar[ActivityReservation | None] = ContextVar(
    "workflow_activity_reservation",
    default=None,
)


class ActivityCoordinator:
    _registry_lock = threading.Lock()
    _registry: weakref.WeakValueDictionary[Path, ActivityCoordinator] = (
        weakref.WeakValueDictionary()
    )

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._lock_root = self.artifact_root / ".activity-locks"
        self._state_lock = threading.RLock()
        self._starts = 0
        self._resumes: dict[str, int] = {}
        self._deletions: set[str] = set()

    @classmethod
    def for_artifact_root(cls, artifact_root: Path) -> ActivityCoordinator:
        root = Path(artifact_root).expanduser().resolve()
        with cls._registry_lock:
            coordinator = cls._registry.get(root)
            if coordinator is None:
                coordinator = cls(root)
                cls._registry[root] = coordinator
            return coordinator

    def reserve_start(self) -> ActivityReservation:
        with self._state_lock:
            if self._deletions:
                raise RunDeletionBusy()
            try:
                lock = _AdvisoryLock(self._lock_root / "start-delete.lock", shared=True)
            except BlockingIOError as exc:
                raise RunDeletionBusy() from exc
            self._starts += 1
            return ActivityReservation(self, "start", None, (lock,))

    def reserve_resume(self, run_id: str) -> ActivityReservation:
        with self._state_lock:
            if run_id in self._deletions:
                raise RunDeletionBusy(run_id)
            if self._resumes.get(run_id):
                raise RunBusy(run_id)
            locks: list[_AdvisoryLock] = []
            try:
                locks.append(
                    _AdvisoryLock(
                        self._deletion_lock_path(run_id),
                        shared=True,
                    )
                )
            except BlockingIOError as exc:
                raise RunDeletionBusy(run_id) from exc
            try:
                locks.append(
                    _AdvisoryLock(self._run_lock_path(run_id), shared=False)
                )
            except BlockingIOError as exc:
                for lock in reversed(locks):
                    lock.release()
                raise RunBusy(run_id) from exc
            self._resumes[run_id] = self._resumes.get(run_id, 0) + 1
            return ActivityReservation(self, "resume", run_id, tuple(locks))

    def reserve_deletion(self, run_id: str) -> ActivityReservation:
        with self._state_lock:
            if self._starts or self._resumes.get(run_id) or run_id in self._deletions:
                raise RunBusy(run_id)
            locks: list[_AdvisoryLock] = []
            try:
                locks.append(
                    _AdvisoryLock(
                        self._lock_root / "start-delete.lock",
                        shared=False,
                    )
                )
                locks.append(
                    _AdvisoryLock(
                        self._deletion_lock_path(run_id),
                        shared=False,
                    )
                )
                locks.append(_AdvisoryLock(self._run_lock_path(run_id), shared=False))
            except BlockingIOError as exc:
                for lock in reversed(locks):
                    lock.release()
                raise RunBusy(run_id) from exc
            self._deletions.add(run_id)
            return ActivityReservation(self, "delete", run_id, tuple(locks))

    @contextmanager
    def start_execution(self) -> Iterator[None]:
        active = _ACTIVE_RESERVATION.get()
        if active is not None and active._coordinator is self and active.kind == "start":
            yield
            return
        with self.reserve_start() as reservation:
            with reservation.activate():
                yield

    @contextmanager
    def resume_execution(self, run_id: str) -> Iterator[None]:
        active = _ACTIVE_RESERVATION.get()
        if (
            active is not None
            and active._coordinator is self
            and active.kind == "resume"
            and active.run_id == run_id
        ):
            yield
            return
        with self.reserve_resume(run_id) as reservation:
            with reservation.activate():
                yield

    def _release(self, reservation: ActivityReservation) -> None:
        with self._state_lock:
            if reservation.kind == "start":
                self._starts -= 1
            elif reservation.kind == "resume":
                assert reservation.run_id is not None
                remaining = self._resumes[reservation.run_id] - 1
                if remaining:
                    self._resumes[reservation.run_id] = remaining
                else:
                    del self._resumes[reservation.run_id]
            else:
                assert reservation.run_id is not None
                self._deletions.remove(reservation.run_id)
            for lock in reversed(reservation._locks):
                lock.release()

    def _run_lock_path(self, run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self._lock_root / f"run-{digest}.lock"

    def _deletion_lock_path(self, run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self._lock_root / f"delete-{digest}.lock"


__all__ = [
    "ActivityCoordinator",
    "ActivityReservation",
    "RunBusy",
    "RunDeletionBusy",
    "UnsupportedPlatformError",
    "WorkbenchAlreadyRunningError",
    "WorkbenchInstanceGuard",
    "require_supported_platform",
]
