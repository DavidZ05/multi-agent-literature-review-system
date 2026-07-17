from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore


_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def export_audit_bundle(
    store: SQLiteWorkflowStore,
    artifact_store: LocalArtifactStore,
    run_id: str,
    output_path: Path,
    *,
    include_pdfs: bool = True,
) -> dict[str, object]:
    activity = ActivityCoordinator.for_artifact_root(artifact_store.root)
    with activity.resume_execution(run_id):
        return _export_audit_bundle(
            store,
            artifact_store,
            run_id,
            output_path,
            include_pdfs=include_pdfs,
        )


def _export_audit_bundle(
    store: SQLiteWorkflowStore,
    artifact_store: LocalArtifactStore,
    run_id: str,
    output_path: Path,
    *,
    include_pdfs: bool,
) -> dict[str, object]:
    run = store.get_run(run_id)
    run_root = artifact_store.root.resolve() / "runs" / run_id
    files: list[tuple[str, bytes]] = []
    if run_root.is_dir():
        for path in sorted(run_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(run_root).as_posix()
            if relative.startswith("exports/"):
                continue
            if not include_pdfs and relative.startswith("documents/"):
                continue
            files.append((f"artifacts/{relative}", path.read_bytes()))
    document_history, archived_chunks = _load_document_history(run_root)
    current_chunks = store.list_evidence_chunks(run_id)
    chunks_by_id = {
        item.chunk_id: item.to_dict()
        for item in current_chunks
    }
    for item in archived_chunks:
        chunks_by_id.setdefault(str(item["chunk_id"]), item)

    audit = {
        "format": "literature-review-audit-v1",
        "run": run.to_dict(),
        "events": [event.to_dict() for event in store.list_events(run_id)],
        "discovery_attempts": [
            item.to_dict() for item in store.list_discovery_attempts(run_id)
        ],
        "candidates": [
            item.to_dict() for item in store.list_candidates(run_id)
        ],
        "corpus_decisions": [
            {
                "decision": decision.to_dict(),
                "details": details,
            }
            for decision, details in store.list_corpus_decisions(run_id)
        ],
        "documents": [item.to_dict() for item in store.list_documents(run_id)],
        "document_history": document_history,
        "evidence_chunks": [
            chunks_by_id[chunk_id] for chunk_id in sorted(chunks_by_id)
        ],
        "claims": [item.to_dict() for item in store.list_claims(run_id)],
        "verifications": [
            item.to_dict() for item in store.list_claim_verifications(run_id)
        ],
        "evidence_review_decisions": [
            item.to_dict() for item in store.list_evidence_review_decisions(run_id)
        ],
        "files": [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for path, content in files
        ],
    }
    manifest = (
        json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        entries = [("audit/manifest.json", manifest), *files]
        for path, content in sorted(entries, key=lambda item: item[0]):
            _write_zip_entry(archive, path, content)
    return {
        "run_id": run_id,
        "output_path": str(output_path),
        "include_pdfs": include_pdfs,
        "file_count": len(files) + 1,
        "sha256": _hash_path(output_path),
    }


def _load_document_history(
    run_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    history_root = run_root / "evidence" / "history" / "documents"
    documents: list[dict[str, object]] = []
    chunks: list[dict[str, object]] = []
    if not history_root.is_dir():
        return documents, chunks
    for path in sorted(history_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        document = payload.get("document")
        if isinstance(document, dict):
            documents.append(
                {
                    "document": document,
                    "archived_pdf_path": payload.get("archived_pdf_path"),
                }
            )
        archived = payload.get("chunks", [])
        if isinstance(archived, list):
            chunks.extend(item for item in archived if isinstance(item, dict))
    return documents, chunks


def _write_zip_entry(archive: ZipFile, name: str, content: bytes) -> None:
    info = ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["export_audit_bundle"]
