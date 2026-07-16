from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from src.literature_review.models import utc_now_iso


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactPathError(ArtifactStoreError):
    pass


@dataclass(frozen=True)
class ArtifactRecord:
    run_id: str
    relative_path: str
    absolute_path: Path
    sha256: str
    size_bytes: int
    created_at: str


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _target(self, run_id: str, relative_path: str) -> Path:
        if not re.fullmatch(r"run_[0-9a-f]{32}", run_id):
            raise ArtifactPathError("invalid run_id")
        candidate = Path(relative_path)
        if candidate.is_absolute() or not relative_path.strip():
            raise ArtifactPathError("artifact path must be nonempty and relative")
        run_root = (self.root / "runs" / run_id).resolve()
        target = (run_root / candidate).resolve()
        if not target.is_relative_to(run_root) or target == run_root:
            raise ArtifactPathError("artifact path escapes the run directory")
        return target

    def _write_bytes(
        self, run_id: str, relative_path: str, content: bytes
    ) -> ArtifactRecord:
        target = self._target(run_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, delete=False
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return ArtifactRecord(
            run_id=run_id,
            relative_path=relative_path,
            absolute_path=target,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            created_at=utc_now_iso(),
        )

    def write_text(
        self, run_id: str, relative_path: str, content: str
    ) -> ArtifactRecord:
        return self._write_bytes(run_id, relative_path, content.encode("utf-8"))

    def write_bytes(
        self, run_id: str, relative_path: str, content: bytes
    ) -> ArtifactRecord:
        if not isinstance(content, bytes):
            raise TypeError("binary artifact content must be bytes")
        return self._write_bytes(run_id, relative_path, content)

    def write_json(self, run_id: str, relative_path: str, data: Any) -> ArtifactRecord:
        content = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        return self.write_text(run_id, relative_path, content)

    def read_text(self, run_id: str, relative_path: str) -> str:
        return self._target(run_id, relative_path).read_text(encoding="utf-8")

    def read_bytes(self, run_id: str, relative_path: str) -> bytes:
        return self._target(run_id, relative_path).read_bytes()

    def read_json(self, run_id: str, relative_path: str) -> Any:
        return json.loads(self.read_text(run_id, relative_path))

    def exists(self, run_id: str, relative_path: str) -> bool:
        return self._target(run_id, relative_path).is_file()

    def path_for(self, run_id: str, relative_path: str) -> Path:
        return self._target(run_id, relative_path)

    def hash_file(self, run_id: str, relative_path: str) -> str:
        target = self._target(run_id, relative_path)
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


__all__ = [
    "ArtifactPathError",
    "ArtifactRecord",
    "ArtifactStoreError",
    "LocalArtifactStore",
]
