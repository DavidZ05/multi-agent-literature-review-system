from __future__ import annotations

from pathlib import Path

from src.literature_review.exporting import export_audit_bundle
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workbench.commands import (
    equivalent_command,
    scoped_command_arguments,
)


class ExportWorkbenchService:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        artifact_root: Path,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root

    def export_run(
        self,
        run_id: str,
        *,
        include_pdfs: bool = True,
    ) -> dict[str, object]:
        output_path = (
            self.artifact_root
            / "runs"
            / run_id
            / "exports"
            / f"{run_id}-audit.zip"
        )
        result = export_audit_bundle(
            self.store,
            LocalArtifactStore(self.artifact_root),
            run_id,
            output_path,
            include_pdfs=include_pdfs,
        )
        result["equivalent_command"] = equivalent_command(
            *scoped_command_arguments(self.store, self.artifact_root),
            "export",
            run_id,
            f"--output={output_path}",
            *(() if include_pdfs else ("--no-pdfs",)),
        )
        return result


__all__ = ["ExportWorkbenchService"]
