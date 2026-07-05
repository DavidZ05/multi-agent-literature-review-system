from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
from uuid import uuid4

from src.literature_review.activity import (
    ActivityCoordinator,
    RunBusy,
    RunDeletionBusy,
)


_RUN_ID_PATTERN = re.compile(r"run_[0-9a-f]{32}")
_QUARANTINE_NAME_PATTERN = re.compile(
    r"(run_[0-9a-f]{32})--delete-[0-9a-f]{32}"
)


@dataclass(frozen=True)
class ArtifactDeletionHandle:
    run_id: str
    source_path: Path
    quarantine_path: Path
    _manager: ArtifactDeletionManager = field(repr=False, compare=False)

    def restore(self) -> None:
        self._manager._restore(self)

    def purge(self) -> None:
        self._manager._purge(self)


@dataclass(frozen=True)
class ArtifactReconciliationReport:
    purged: int = 0
    restored: int = 0
    unresolved: int = 0


class ArtifactDeletionManager:
    def __init__(self, artifact_root: Path) -> None:
        resolved_root = Path(artifact_root).expanduser().resolve()
        if resolved_root.exists() and not resolved_root.is_dir():
            raise ValueError("artifact root must be a directory")
        self.artifact_root = resolved_root
        self._runs_path = self.artifact_root / "runs"
        self._pending_path = self.artifact_root / ".delete-pending"

    def quarantine(self, run_id: str) -> ArtifactDeletionHandle | None:
        self._validate_run_id(run_id)
        runs = self._resolve_parent_directory(
            self._runs_path,
            "run artifacts parent",
        )
        source = self._resolve_under_root(
            runs / run_id,
            "run artifact path",
        )
        if not source.exists():
            return None
        if source.is_symlink() or not source.is_dir():
            raise ValueError("run artifact path must be a directory")

        pending = self._resolve_parent_directory(
            self._pending_path,
            "delete-pending path",
        )
        pending.mkdir(parents=True, exist_ok=True)
        pending = self._resolve_parent_directory(pending, "delete-pending path")
        self._require_same_filesystem(source, pending)

        while True:
            quarantine = pending / f"{run_id}--delete-{uuid4().hex}"
            quarantine = self._resolve_under_root(
                quarantine,
                "quarantine path",
            )
            if not quarantine.exists() and not quarantine.is_symlink():
                break

        self._resolve_parent_directory(self._runs_path, "run artifacts parent")
        self._resolve_parent_directory(self._pending_path, "delete-pending path")
        self._resolve_under_root(source, "run artifact path")
        self._resolve_under_root(quarantine, "quarantine path")
        try:
            source.replace(quarantine)
        except FileNotFoundError:
            if not source.exists() and not source.is_symlink():
                return None
            raise
        return ArtifactDeletionHandle(
            run_id=run_id,
            source_path=source,
            quarantine_path=quarantine,
            _manager=self,
        )

    def cleanup_pending(
        self,
        *,
        exclude_run_ids: Iterable[str] = (),
    ) -> int:
        excluded = frozenset(exclude_run_ids)
        for run_id in excluded:
            self._validate_run_id(run_id)

        pending = self._resolve_parent_directory(
            self._pending_path,
            "delete-pending path",
        )
        if not pending.exists():
            return 0

        removed = 0
        for candidate in pending.iterdir():
            match = _QUARANTINE_NAME_PATTERN.fullmatch(candidate.name)
            if match is None or match.group(1) in excluded:
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            self._resolve_under_root(candidate, "quarantine path")
            shutil.rmtree(candidate)
            removed += 1
        return removed

    def reconcile_pending(
        self,
        run_exists: Callable[[str], bool],
        *,
        activity: ActivityCoordinator | None = None,
    ) -> ArtifactReconciliationReport:
        if not callable(run_exists):
            raise TypeError("run_exists must be callable")
        coordinator = (
            ActivityCoordinator.for_artifact_root(self.artifact_root)
            if activity is None
            else activity
        )
        if coordinator.artifact_root != self.artifact_root:
            raise ValueError(
                "activity coordinator must match the configured artifact root"
            )

        pending = self._resolve_parent_directory(
            self._pending_path,
            "delete-pending path",
        )
        if not pending.exists():
            return ArtifactReconciliationReport()

        grouped: dict[str, list[Path]] = {}
        for candidate in pending.iterdir():
            match = _QUARANTINE_NAME_PATTERN.fullmatch(candidate.name)
            if match is not None:
                grouped.setdefault(match.group(1), []).append(candidate)

        purged = 0
        restored = 0
        unresolved = 0
        for run_id, candidates in grouped.items():
            try:
                reservation = coordinator.reserve_deletion(run_id)
            except (RunBusy, RunDeletionBusy):
                unresolved += len(candidates)
                continue

            try:
                exists = run_exists(run_id)
                if not isinstance(exists, bool):
                    raise TypeError("run_exists must return a boolean")
                if not exists:
                    for candidate in candidates:
                        if candidate.is_symlink() or not candidate.is_dir():
                            unresolved += 1
                            continue
                        self._resolve_under_root(candidate, "quarantine path")
                        shutil.rmtree(candidate)
                        purged += 1
                    continue

                source = self._runs_path / run_id
                if (
                    source.exists()
                    or source.is_symlink()
                    or len(candidates) != 1
                ):
                    unresolved += len(candidates)
                    continue

                quarantine = candidates[0]
                if quarantine.is_symlink() or not quarantine.is_dir():
                    unresolved += 1
                    continue
                runs = self._resolve_parent_directory(
                    self._runs_path,
                    "run artifacts parent",
                )
                runs.mkdir(parents=True, exist_ok=True)
                handle = ArtifactDeletionHandle(
                    run_id=run_id,
                    source_path=source,
                    quarantine_path=quarantine,
                    _manager=self,
                )
                handle.restore()
                restored += 1
            finally:
                reservation.release()

        return ArtifactReconciliationReport(
            purged=purged,
            restored=restored,
            unresolved=unresolved,
        )

    def _restore(self, handle: ArtifactDeletionHandle) -> None:
        source, quarantine = self._validated_handle_paths(handle)
        source_parent = self._resolve_parent_directory(
            source.parent,
            "run artifacts parent",
        )
        if source.exists() or source.is_symlink():
            raise FileExistsError(f"run artifact path already exists: {source}")
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise FileNotFoundError(f"quarantine directory not found: {quarantine}")

        self._require_same_filesystem(quarantine, source_parent)
        self._resolve_parent_directory(source.parent, "run artifacts parent")
        self._resolve_parent_directory(
            quarantine.parent,
            "delete-pending path",
        )
        self._resolve_under_root(source, "run artifact path")
        self._resolve_under_root(quarantine, "quarantine path")
        quarantine.replace(source)

    def _purge(self, handle: ArtifactDeletionHandle) -> None:
        _, quarantine = self._validated_handle_paths(handle)
        if not quarantine.exists() and not quarantine.is_symlink():
            return
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise ValueError("quarantine path must be a directory")

        self._resolve_under_root(quarantine, "quarantine path")
        shutil.rmtree(quarantine)

    def _validated_handle_paths(
        self,
        handle: ArtifactDeletionHandle,
    ) -> tuple[Path, Path]:
        if not isinstance(handle, ArtifactDeletionHandle) or handle._manager is not self:
            raise ValueError("deletion handle belongs to another manager")
        self._validate_run_id(handle.run_id)

        expected_source = self._runs_path / handle.run_id
        if handle.source_path != expected_source:
            raise ValueError("deletion handle has an invalid source path")
        if handle.quarantine_path.parent != self._pending_path:
            raise ValueError("deletion handle has an invalid quarantine path")
        match = _QUARANTINE_NAME_PATTERN.fullmatch(handle.quarantine_path.name)
        if match is None or match.group(1) != handle.run_id:
            raise ValueError("deletion handle has an invalid quarantine name")

        self._resolve_parent_directory(
            handle.quarantine_path.parent,
            "delete-pending path",
        )
        source = self._resolve_under_root(handle.source_path, "run artifact path")
        quarantine = self._resolve_under_root(
            handle.quarantine_path,
            "quarantine path",
        )
        return source, quarantine

    def _resolve_under_root(self, path: Path, label: str) -> Path:
        try:
            relative_path = path.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ValueError(
                f"{label} escapes configured artifact root"
            ) from exc
        if not relative_path.parts:
            raise ValueError(f"{label} escapes configured artifact root")

        current = self.artifact_root
        for part in relative_path.parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"{label} must not traverse symlinks")

        resolved = path.resolve()
        if (
            resolved == self.artifact_root
            or not resolved.is_relative_to(self.artifact_root)
        ):
            raise ValueError(f"{label} escapes configured artifact root")
        return resolved

    def _resolve_parent_directory(self, path: Path, label: str) -> Path:
        resolved = self._resolve_under_root(path, label)
        if resolved.exists() and not resolved.is_dir():
            raise ValueError(f"{label} must be a directory")
        return resolved

    @staticmethod
    def _require_same_filesystem(source: Path, destination_dir: Path) -> None:
        if source.stat().st_dev != destination_dir.stat().st_dev:
            raise OSError("artifact quarantine must stay on the same filesystem")

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or _RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("invalid run_id")


__all__ = [
    "ArtifactDeletionHandle",
    "ArtifactDeletionManager",
    "ArtifactReconciliationReport",
]
