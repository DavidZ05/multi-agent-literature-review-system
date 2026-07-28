from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from src.literature_review.corpus import load_papers
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
)
from src.literature_review.storage import SQLiteWorkflowStore


class ApprovalService:
    def __init__(self, store: SQLiteWorkflowStore) -> None:
        self.store = store

    def approve(
        self,
        run_id: str,
        candidate_id: str,
        *,
        reason: str,
        category: str,
        contribution: str,
        tags: tuple[str, ...],
        actor: str = "human",
    ) -> CorpusDecision:
        if not category.strip():
            raise ValueError("category is required for approval")
        if not contribution.strip():
            raise ValueError("contribution is required for approval")
        if not tags or any(not tag.strip() for tag in tags):
            raise ValueError("at least one nonblank tag is required for approval")
        return self._decide(
            run_id,
            candidate_id,
            CandidateStatus.APPROVED,
            reason,
            actor,
            {
                "category": category.strip(),
                "contribution": contribution.strip(),
                "tags": [tag.strip() for tag in tags],
            },
        )

    def reject(
        self,
        run_id: str,
        candidate_id: str,
        *,
        reason: str,
        actor: str = "human",
    ) -> CorpusDecision:
        return self._decide(
            run_id,
            candidate_id,
            CandidateStatus.REJECTED,
            reason,
            actor,
            {},
        )

    def defer(
        self,
        run_id: str,
        candidate_id: str,
        *,
        reason: str,
        actor: str = "human",
    ) -> CorpusDecision:
        return self._decide(
            run_id,
            candidate_id,
            CandidateStatus.DEFERRED,
            reason,
            actor,
            {},
        )

    def _decide(
        self,
        run_id: str,
        candidate_id: str,
        status: CandidateStatus,
        reason: str,
        actor: str,
        details: dict[str, object],
    ) -> CorpusDecision:
        if not reason.strip():
            raise ValueError("reason is required")
        candidate = self.store.get_candidate(run_id, candidate_id)
        details = {
            **details,
            "candidate_snapshot": candidate.approval_snapshot(),
            "candidate_fingerprint": candidate.approval_fingerprint(),
        }
        decision = CorpusDecision.create(
            run_id,
            candidate_id,
            status,
            reason.strip(),
            actor,
        )
        self.store.append_corpus_decision(decision, details=details)
        return decision

    def build_approved_corpus(
        self,
        run_id: str,
        seed_path: Path,
    ) -> list[dict[str, object]]:
        seed_records = json.loads(Path(seed_path).read_text(encoding="utf-8"))
        if not isinstance(seed_records, list):
            raise ValueError("seed corpus must contain a JSON array")
        details_by_candidate: dict[str, dict[str, object]] = {}
        for decision, details in self.store.list_corpus_decisions(run_id):
            if decision.status == CandidateStatus.APPROVED:
                details_by_candidate[decision.candidate_id] = details
        used_keys = {str(item["citation_key"]) for item in seed_records}
        records = list(seed_records)
        for item in self.store.list_candidates(run_id, status=CandidateStatus.APPROVED):
            details = details_by_candidate[item.candidate_id]
            item = self._approved_snapshot(item, details)
            citation_key = self._citation_key(item, used_keys)
            used_keys.add(citation_key)
            record = {
                "citation_key": citation_key,
                "title": item.title,
                "authors": list(item.authors),
                "year": item.year,
                "venue": item.venue or "Unknown venue",
                "url": item.source_urls[0],
                "category": details["category"],
                "contribution": details["contribution"],
                "evidence": "metadata verified; full-text verification pending",
                "tags": details["tags"],
            }
            if item.open_access_pdf_url:
                record["open_access_pdf_url"] = item.open_access_pdf_url
            records.append(record)
        with TemporaryDirectory() as temporary:
            validation_path = Path(temporary) / "approved_corpus.json"
            validation_path.write_text(
                json.dumps(records, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            load_papers(validation_path)
        return records

    @staticmethod
    def _approved_snapshot(
        current: CandidatePaper,
        details: dict[str, object],
    ) -> CandidatePaper:
        snapshot = details.get("candidate_snapshot")
        fingerprint = details.get("candidate_fingerprint")
        if snapshot is None and fingerprint is None:
            return current
        if not isinstance(snapshot, dict) or not isinstance(fingerprint, str):
            raise ValueError("approved candidate snapshot is malformed")
        approved = CandidatePaper.from_dict(snapshot)
        if approved.approval_fingerprint() != fingerprint:
            raise ValueError("approved candidate snapshot fingerprint mismatch")
        if current.approval_fingerprint() != fingerprint:
            raise ValueError("approved candidate metadata changed after human review")
        return approved

    @staticmethod
    def _citation_key(item, used_keys: set[str]) -> str:
        surname = re.sub(r"[^a-z]", "", item.authors[0].split()[-1].lower())
        title_tokens = re.findall(r"[a-z0-9]+", item.title.lower())
        significant = next(
            (
                token
                for token in title_tokens
                if token not in {"a", "an", "the", "of", "for", "and", "in"}
            ),
            "paper",
        )
        base = f"{surname}{item.year}{significant}"
        if base not in used_keys:
            return base
        suffix = "a"
        while f"{base}{suffix}" in used_keys:
            suffix = chr(ord(suffix) + 1)
        return f"{base}{suffix}"


__all__ = ["ApprovalService"]
