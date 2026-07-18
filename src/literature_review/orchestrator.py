from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Callable

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.corpus import load_papers
from src.literature_review.plugins import AgentFactory, build_agent_factory


class Orchestrator:
    """Coordinates the full multi-agent survey workflow."""

    def __init__(
        self,
        corpus_path: Path,
        output_dir: Path,
        runtime_config: AgentRuntimeConfig | None = None,
        run_id: str | None = None,
        api_client: Any | None = None,
        agent_factory: AgentFactory | None = None,
        initial_review_feedback: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.corpus_path = corpus_path
        self.output_dir = output_dir
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.run_id = run_id
        self.api_client = api_client
        self.agent_factory = agent_factory or build_agent_factory()
        self.initial_review_feedback = initial_review_feedback
        self.event_callback = event_callback
        create = self.agent_factory.create
        self.search_agent = create("search", self.runtime_config, api_client)
        self.writer_agent = create("writer", self.runtime_config, api_client)
        self.reviewer_agent = create("reviewer", self.runtime_config, api_client)
        self.domain_expert_agent = create(
            "domain_expert", self.runtime_config, api_client
        )
        self.structure_mentor_agent = create(
            "structure_mentor", self.runtime_config, api_client
        )
        self.review_synthesizer_agent = create(
            "review_synthesizer", self.runtime_config, api_client
        )
        self.polish_agent = create("polish", self.runtime_config, api_client)
        self.final_verification_reviewer = create(
            "final_verification", self.runtime_config, api_client
        )
        self.evaluation_reflection_agent = create(
            "evaluation_reflection", self.runtime_config, api_client
        )

    def run(self, max_revision_loops: int = 2) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir = self.output_dir / "intermediate"
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for stale_draft in intermediate_dir.glob("writer_draft_v*.md"):
            stale_draft.unlink()

        papers = load_papers(self.corpus_path)
        self._write_json(
            self.output_dir / "runtime_config.json", self.runtime_config.public_dict()
        )
        search_report = self.search_agent.run(papers)
        self._write_json(intermediate_dir / "search_report.json", search_report)
        self._emit("search", {"records_included": search_report["records_included"]})

        draft = ""
        review_report: dict[str, Any] = {}
        revision_log = []
        review_feedback: dict[str, Any] | None = self.initial_review_feedback
        previous_draft: str | None = None
        for attempt in range(max_revision_loops + 1):
            draft = self._run_writer(search_report, review_feedback)
            (intermediate_dir / f"writer_draft_v{attempt + 1}.md").write_text(
                draft,
                encoding="utf-8",
            )
            iteration_dir = intermediate_dir / "iterations" / f"iteration_{attempt + 1:03d}"
            iteration_dir.mkdir(parents=True, exist_ok=True)
            (iteration_dir / "writer_draft.md").write_text(draft, encoding="utf-8")
            self._emit("writer", {"iteration": attempt + 1})

            citation_audit = self.reviewer_agent.review(draft, papers)
            domain_review = self.domain_expert_agent.review(
                draft, papers, search_report
            )
            structure_review = self.structure_mentor_agent.review(draft)
            revision_plan = self.review_synthesizer_agent.synthesize(
                [citation_audit, domain_review, structure_review]
            )

            self._write_json(intermediate_dir / "citation_audit.json", citation_audit)
            self._write_json(intermediate_dir / "domain_review.json", domain_review)
            self._write_json(
                intermediate_dir / "structure_review.json", structure_review
            )
            self._write_json(intermediate_dir / "revision_plan.json", revision_plan)
            self._write_json(iteration_dir / "citation_audit.json", citation_audit)
            self._write_json(iteration_dir / "domain_review.json", domain_review)
            self._write_json(iteration_dir / "structure_review.json", structure_review)
            self._write_json(iteration_dir / "revision_plan.json", revision_plan)
            self._emit(
                "expert_review_panel",
                {"iteration": attempt + 1, "status": revision_plan["status"]},
            )

            review_report = {
                "agent": "Expert Review Panel",
                "status": revision_plan["status"],
                "expert_panel": {
                    "citation_audit": citation_audit,
                    "domain_review": domain_review,
                    "structure_review": structure_review,
                },
                "revision_plan": revision_plan,
                "unknown_citations": citation_audit["unknown_citations"],
                "missing_citations": citation_audit["missing_citations"],
                "unsupported_claims": citation_audit["unsupported_claims"],
                "missing_sections": citation_audit["missing_sections"],
            }
            revision_log.append(
                {
                    "iteration": attempt + 1,
                    "status": review_report["status"],
                    "unknown_citations": review_report["unknown_citations"],
                    "missing_citation_count": len(
                        review_report["missing_citations"]
                    ),
                    "unsupported_claim_count": len(review_report["unsupported_claims"]),
                    "missing_sections": review_report["missing_sections"],
                    "blocking_agents": revision_plan["blocking_agents"],
                }
            )
            if review_report["status"] == "accepted":
                self._emit("review_accepted", {"iteration": attempt + 1})
                break
            if previous_draft is not None and draft == previous_draft:
                review_report["revision_stalled"] = True
                revision_log[-1]["revision_stalled"] = True
                self._emit("revision_stalled", {"iteration": attempt + 1})
                break
            previous_draft = draft
            review_feedback = review_report
            self._emit("revision_requested", {"iteration": attempt + 1})

        (intermediate_dir / "writer_draft.md").write_text(draft, encoding="utf-8")
        self._write_json(self.output_dir / "review_report.json", review_report)
        self._write_json(
            self.output_dir / "revision_log.json", {"iterations": revision_log}
        )

        if review_report["status"] == "accepted":
            final = self.polish_agent.run(draft)
            self._emit("polish", {})
        else:
            final = draft

        polish_verification = self.final_verification_reviewer.review(
            draft, final, papers
        )
        if polish_verification["status"] != "accepted":
            final = draft
            final_verification = self.final_verification_reviewer.review(
                draft,
                final,
                papers,
            )
            final_verification["final_action"] = (
                "polish_output_rejected; accepted draft retained"
            )
            final_verification["rejected_polish_verification"] = polish_verification
        else:
            final_verification = polish_verification
            final_verification["final_action"] = "polish_output_accepted"
        self._emit(
            "final_verification",
            {
                "status": final_verification["status"],
                "final_action": final_verification["final_action"],
            },
        )

        self._write_json(
            self.output_dir / "final_verification.json", final_verification
        )
        evaluation_report = self.evaluation_reflection_agent.evaluate(
            search_report,
            review_report,
            final_verification,
            revision_log,
        )
        self._write_json(self.output_dir / "evaluation_report.json", evaluation_report)
        self._emit("evaluation_reflection", {})
        (self.output_dir / "reflection_log.md").write_text(
            self.evaluation_reflection_agent.to_markdown(evaluation_report),
            encoding="utf-8",
        )
        (self.output_dir / "survey.md").write_text(final, encoding="utf-8")

        result = {
            "status": review_report["status"]
            if final_verification["status"] == "accepted"
            else final_verification["status"],
            "survey": str(self.output_dir / "survey.md"),
            "review_report": str(self.output_dir / "review_report.json"),
            "final_verification": str(self.output_dir / "final_verification.json"),
            "evaluation_report": str(self.output_dir / "evaluation_report.json"),
        }
        if self.run_id is not None:
            result["run_id"] = self.run_id
        return result

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")

    def _emit(self, stage: str, payload: dict[str, Any]) -> None:
        if self.event_callback is not None:
            self.event_callback(stage, payload)

    def _run_writer(
        self,
        search_report: dict[str, Any],
        review_feedback: dict[str, Any] | None,
    ) -> str:
        signature = inspect.signature(self.writer_agent.run)
        if "review_feedback" in signature.parameters:
            return self.writer_agent.run(search_report, review_feedback=review_feedback)
        return self.writer_agent.run(search_report)


__all__ = ["Orchestrator"]
