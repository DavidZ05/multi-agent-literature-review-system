from __future__ import annotations

from pathlib import Path
import shlex

from src.literature_review.storage import SQLiteWorkflowStore


COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")


def equivalent_command(*arguments: str) -> str:
    return shlex.join([*COMMAND_PREFIX, *arguments])


def scoped_command_arguments(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
) -> tuple[str, str]:
    return (
        f"--db={store.path.expanduser().resolve()}",
        f"--artifacts={artifact_root.expanduser().resolve()}",
    )


__all__ = ["COMMAND_PREFIX", "equivalent_command", "scoped_command_arguments"]
