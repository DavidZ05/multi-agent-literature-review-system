import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from src.literature_review.exporting import export_audit_bundle
from src.literature_review.models import ResearchRun
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore


class AuditExportTests(unittest.TestCase):
    def test_export_is_reproducible_and_manifest_hashes_artifacts(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SQLiteWorkflowStore(root / "workflow.db")
            store.initialize()
            run = ResearchRun.create("Agent memory")
            store.create_run(run)
            artifacts = LocalArtifactStore(root / "artifacts")
            survey = artifacts.write_text(run.run_id, "final/survey.md", "# Review\n")
            artifacts.write_bytes(run.run_id, "documents/paper.pdf", b"%PDF-1.7\n")
            first = export_audit_bundle(
                store,
                artifacts,
                run.run_id,
                root / "first.zip",
            )
            second = export_audit_bundle(
                store,
                artifacts,
                run.run_id,
                root / "second.zip",
            )

            self.assertEqual(first["sha256"], second["sha256"])
            with ZipFile(root / "first.zip") as archive:
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                manifest = json.loads(archive.read("audit/manifest.json"))
                files = {item["path"]: item for item in manifest["files"]}
                self.assertEqual(
                    files["artifacts/final/survey.md"]["sha256"],
                    survey.sha256,
                )
                self.assertIn("artifacts/documents/paper.pdf", files)


if __name__ == "__main__":
    unittest.main()
