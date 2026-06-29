from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from src.literature_review.base import RuntimeAwareAgent
from src.literature_review.config import AgentAPISettings, AgentRuntimeConfig
from src.literature_review.corpus import load_papers
from src.literature_review.search import SearchAgent
from src.literature_review.writing import PolishAgent, WriterAgent


class ReviewerAgent(RuntimeAwareAgent):
    """Checks citation integrity and basic report structure."""

    citation_pattern = re.compile(r"\[([a-z][a-z0-9]+(?:[a-z0-9])?)\]")
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "these",
        "this",
        "to",
        "with",
    }

    def review(self, markdown: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
        valid_keys = {paper["citation_key"] for paper in papers}
        papers_by_key = {paper["citation_key"]: paper for paper in papers}
        cited_keys = sorted(set(self.citation_pattern.findall(markdown)))
        unknown = [key for key in cited_keys if key not in valid_keys]
        unsupported_claims = self._find_unsupported_claims(markdown, papers_by_key)
        required_markers = [
            "## Abstract",
            "## References",
            "Implications for Multi-Agent Literature Review Systems",
        ]
        missing_sections = [
            marker
            for marker in required_markers
            if marker not in markdown
        ]
        status = (
            "accepted"
            if not unknown and not missing_sections and not unsupported_claims
            else "revise"
        )
        return {
            "agent": "Citation Auditor Agent",
            "backend": self.backend_note(),
            "status": status,
            "cited_keys": cited_keys,
            "unknown_citations": unknown,
            "unsupported_claims": unsupported_claims,
            "missing_sections": missing_sections,
            "recommendations": self._recommendations(
                unknown,
                missing_sections,
                unsupported_claims,
            ),
        }

    def _recommendations(
        self,
        unknown: list[str],
        missing: list[str],
        unsupported_claims: list[dict[str, Any]],
    ) -> list[str]:
        recommendations = []
        if unknown:
            recommendations.append("Remove or replace citations not present in data/papers.json.")
        if missing:
            recommendations.append("Restore required survey sections before final polish.")
        if unsupported_claims:
            recommendations.append(
                "Revise claims whose wording is not aligned with the cited source metadata."
            )
        if not recommendations:
            recommendations.append("No blocking citation or structure issues found.")
        return recommendations

    def _find_unsupported_claims(
        self,
        markdown: str,
        papers_by_key: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unsupported = []
        for sentence in self._claim_units(markdown):
            keys = [
                key
                for key in self.citation_pattern.findall(sentence)
                if key in papers_by_key
            ]
            if not keys:
                continue
            claim_tokens = self._tokens(self.citation_pattern.sub("", sentence))
            if len(claim_tokens) < 4:
                continue
            supported = False
            best_overlap: list[str] = []
            for key in keys:
                profile_tokens = self._paper_profile_tokens(papers_by_key[key])
                overlap = sorted(claim_tokens & profile_tokens)
                if len(overlap) > len(best_overlap):
                    best_overlap = overlap
                if len(overlap) >= 3:
                    supported = True
                    break
            if not supported:
                unsupported.append(
                    {
                        "sentence": sentence,
                        "citation_keys": keys,
                        "best_overlap": best_overlap,
                    }
                )
        return unsupported

    def _paper_profile_tokens(self, paper: dict[str, Any]) -> set[str]:
        parts = [
            paper.get("title", ""),
            paper.get("category", ""),
            paper.get("contribution", ""),
            " ".join(paper.get("tags", [])),
        ]
        return self._tokens(" ".join(parts))

    def _tokens(self, text: str) -> set[str]:
        raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", text.lower())
        return {
            self._stem(token)
            for token in raw_tokens
            if len(token) >= 4 and token not in self.stopwords
        }

    def _stem(self, token: str) -> str:
        for suffix in ("ing", "ed", "es", "s"):
            if len(token) > len(suffix) + 4 and token.endswith(suffix):
                return token[: -len(suffix)]
        return token

    def _claim_units(self, markdown: str) -> list[str]:
        body = markdown.split("## References", 1)[0]
        units = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "|", "-", "*")):
                continue
            if not self.citation_pattern.search(stripped):
                continue
            units.append(stripped)
        return units


class DomainExpertAgent(RuntimeAwareAgent):
    """Reviews topical coverage and scholarly framing."""

    def review(
        self,
        markdown: str,
        papers: list[dict[str, Any]],
        search_report: dict[str, Any],
    ) -> dict[str, Any]:
        categories = sorted(search_report["grouped_papers"].keys())
        expected_terms = {
            "memory mechanisms": ["retrieval", "reflection", "hierarchical", "forgetting"],
            "evaluation": ["evaluation", "benchmark", "longmemeval", "memoryagentbench"],
            "multi-agent reliability": ["multi-agent", "reliability", "hallucination"],
            "human governance": ["human-in-the-loop", "verified", "provenance"],
        }
        lower = markdown.lower()
        coverage = {
            area: any(term in lower for term in terms)
            for area, terms in expected_terms.items()
        }
        missing = [area for area, present in coverage.items() if not present]
        status = "accepted" if not missing else "advisory"
        return {
            "agent": "Domain Expert Agent",
            "backend": self.backend_note(),
            "status": status,
            "review_focus": "memory-agent literature coverage and academic framing",
            "paper_count_reviewed": len(papers),
            "categories_reviewed": categories,
            "coverage": coverage,
            "missing_or_weak_areas": missing,
            "recommendations": self._recommendations(missing),
        }

    def _recommendations(self, missing: list[str]) -> list[str]:
        if not missing:
            return ["Coverage is adequate for the selected course-project scope."]
        return [
            f"Strengthen the discussion of {area}."
            for area in missing
        ]


class StructureMentorAgent(RuntimeAwareAgent):
    """Reviews organization, assignment fit, and readability."""

    expected_headings = [
        "## Abstract",
        "## 1. Introduction",
        "## 2. Methodology",
        "## 3. Taxonomy of Agent Memory",
        "## 5. Evaluation",
        "## 6. Reliability Risks",
        "## 7. Implications for Multi-Agent Literature Review Systems",
        "## References",
    ]

    def review(self, markdown: str) -> dict[str, Any]:
        missing = [heading for heading in self.expected_headings if heading not in markdown]
        word_count = len(re.findall(r"\b\w+\b", markdown))
        status = "accepted" if not missing else "advisory"
        return {
            "agent": "Structure Mentor Agent",
            "backend": self.backend_note(),
            "status": status,
            "word_count": word_count,
            "missing_headings": missing,
            "recommendations": self._recommendations(missing, word_count),
        }

    def _recommendations(self, missing: list[str], word_count: int) -> list[str]:
        recommendations = []
        if missing:
            recommendations.append("Restore or rename missing assignment-facing sections.")
        if word_count < 1500:
            recommendations.append("Expand the survey if the assignment expects a full review essay.")
        if not recommendations:
            recommendations.append("Structure is suitable for submission.")
        return recommendations


class ReviewSynthesizerAgent(RuntimeAwareAgent):
    """Combines panel reviews into one revision decision for Writer."""

    blocking_statuses = {"revise"}

    def synthesize(self, reviews: list[dict[str, Any]]) -> dict[str, Any]:
        blocking_reviews = [
            review
            for review in reviews
            if review.get("status") in self.blocking_statuses
        ]
        must_fix = []
        should_fix = []
        for review in reviews:
            target = must_fix if review.get("status") in self.blocking_statuses else should_fix
            for recommendation in review.get("recommendations", []):
                target.append(f"{review['agent']}: {recommendation}")
        return {
            "agent": "Review Synthesizer Agent",
            "backend": self.backend_note(),
            "status": "revise" if blocking_reviews else "accepted",
            "blocking_agents": [review["agent"] for review in blocking_reviews],
            "must_fix": must_fix,
            "should_fix": should_fix,
            "iteration_stop_rule": (
                "Stop when synthesized status is accepted or max_revision_loops is reached."
            ),
        }


class FinalVerificationReviewer(RuntimeAwareAgent):
    """Checks that polish did not introduce new citation or evidence risks."""

    citation_pattern = ReviewerAgent.citation_pattern

    def review(
        self,
        accepted_draft: str,
        polished_markdown: str,
        papers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        before = sorted(set(self.citation_pattern.findall(accepted_draft)))
        after = sorted(set(self.citation_pattern.findall(polished_markdown)))
        new_citations = sorted(set(after) - set(before))
        removed_citations = sorted(set(before) - set(after))
        citation_audit = ReviewerAgent(self.runtime_config).review(polished_markdown, papers)
        status = "accepted"
        if new_citations or citation_audit["status"] != "accepted":
            status = "revise"
        return {
            "agent": "Final Verification Reviewer",
            "backend": self.backend_note(),
            "status": status,
            "citations_before_polish": before,
            "citations_after_polish": after,
            "new_citations_after_polish": new_citations,
            "removed_citations_after_polish": removed_citations,
            "unknown_citations": citation_audit["unknown_citations"],
            "unsupported_claims": citation_audit["unsupported_claims"],
            "missing_sections": citation_audit["missing_sections"],
            "recommendations": self._recommendations(new_citations, citation_audit),
        }

    def _recommendations(
        self,
        new_citations: list[str],
        citation_audit: dict[str, Any],
    ) -> list[str]:
        recommendations = []
        if new_citations:
            recommendations.append("Reject polish output or re-run Writer review; polish added citations.")
        recommendations.extend(citation_audit.get("recommendations", []))
        if not recommendations:
            recommendations.append("Final polish preserved the accepted citation set.")
        return recommendations


class EvaluationReflectionAgent(RuntimeAwareAgent):
    """Scores the run and writes a concise process reflection."""

    def evaluate(
        self,
        search_report: dict[str, Any],
        review_report: dict[str, Any],
        final_verification: dict[str, Any],
        revision_log: list[dict[str, Any]],
    ) -> dict[str, Any]:
        citation_score = 5.0 if not final_verification["unknown_citations"] else 2.0
        support_score = 5.0 if not final_verification["unsupported_claims"] else 3.0
        process_score = 5.0 if len(revision_log) <= 2 else 4.0
        coverage_score = 5.0 if search_report["records_included"] >= 10 else 3.0
        average = round(
            (citation_score + support_score + process_score + coverage_score) / 4,
            2,
        )
        return {
            "agent": "Evaluation / Reflection Agent",
            "backend": self.backend_note(),
            "scores": {
                "citation_integrity": citation_score,
                "claim_source_alignment": support_score,
                "process_control": process_score,
                "literature_coverage": coverage_score,
                "overall": average,
            },
            "revision_iterations": len(revision_log),
            "records_included": search_report["records_included"],
            "final_status": final_verification["status"],
            "reflections": [
                "Structured source memory reduced fabricated-reference risk.",
                "Expert review is useful only when synthesized feedback is passed back to Writer.",
                "Polish must be followed by final verification because style editing can hide evidence drift.",
                "Long-task source expansion should be handled at Search and human checkpoint stages, not by allowing Writer to invent references.",
                "Final artifact review should check configuration-safety notes, especially API key handling and reproducible fallback behavior.",
                "A future API-backed version should keep the same artifact contracts and citation gate.",
            ],
            "next_run_improvements": [
                "Add external search APIs for candidate discovery.",
                "Add full-text PDF claim verification for high-risk claims.",
                "Add an explicit coverage-insufficient status that asks for more papers before Writer proceeds.",
                "Let human reviewers approve corpus additions before Writer uses them.",
            ],
        }

    def to_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Evaluation and Reflection",
            "",
            f"Final status: `{report['final_status']}`",
            f"Records included: {report['records_included']}",
            f"Revision iterations: {report['revision_iterations']}",
            "",
            "## Scores",
        ]
        for name, score in report["scores"].items():
            lines.append(f"- {name}: {float(score):.1f}/5.0")
        lines.extend(["", "## Reflections"])
        lines.extend(f"- {item}" for item in report["reflections"])
        lines.extend(["", "## Next Run Improvements"])
        lines.extend(f"- {item}" for item in report["next_run_improvements"])
        return "\n".join(lines) + "\n"


class Orchestrator:
    """Coordinates the full multi-agent survey workflow."""

    def __init__(
        self,
        corpus_path: Path,
        output_dir: Path,
        runtime_config: AgentRuntimeConfig | None = None,
    ) -> None:
        self.corpus_path = corpus_path
        self.output_dir = output_dir
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.search_agent = SearchAgent(self.runtime_config)
        self.writer_agent = WriterAgent(self.runtime_config)
        self.reviewer_agent = ReviewerAgent(self.runtime_config)
        self.domain_expert_agent = DomainExpertAgent(self.runtime_config)
        self.structure_mentor_agent = StructureMentorAgent(self.runtime_config)
        self.review_synthesizer_agent = ReviewSynthesizerAgent(self.runtime_config)
        self.polish_agent = PolishAgent(self.runtime_config)
        self.final_verification_reviewer = FinalVerificationReviewer(self.runtime_config)
        self.evaluation_reflection_agent = EvaluationReflectionAgent(self.runtime_config)

    def run(self, max_revision_loops: int = 2) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir = self.output_dir / "intermediate"
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for stale_draft in intermediate_dir.glob("writer_draft_v*.md"):
            stale_draft.unlink()

        papers = load_papers(self.corpus_path)
        self._write_json(self.output_dir / "runtime_config.json", self.runtime_config.public_dict())
        search_report = self.search_agent.run(papers)
        self._write_json(intermediate_dir / "search_report.json", search_report)

        draft = ""
        review_report: dict[str, Any] = {}
        revision_log = []
        review_feedback: dict[str, Any] | None = None
        for attempt in range(max_revision_loops + 1):
            draft = self._run_writer(search_report, review_feedback)
            (intermediate_dir / f"writer_draft_v{attempt + 1}.md").write_text(
                draft,
                encoding="utf-8",
            )

            citation_audit = self.reviewer_agent.review(draft, papers)
            domain_review = self.domain_expert_agent.review(draft, papers, search_report)
            structure_review = self.structure_mentor_agent.review(draft)
            revision_plan = self.review_synthesizer_agent.synthesize(
                [citation_audit, domain_review, structure_review]
            )

            self._write_json(intermediate_dir / "citation_audit.json", citation_audit)
            self._write_json(intermediate_dir / "domain_review.json", domain_review)
            self._write_json(intermediate_dir / "structure_review.json", structure_review)
            self._write_json(intermediate_dir / "revision_plan.json", revision_plan)

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
                "unsupported_claims": citation_audit["unsupported_claims"],
                "missing_sections": citation_audit["missing_sections"],
            }
            revision_log.append(
                {
                    "iteration": attempt + 1,
                    "status": review_report["status"],
                    "unknown_citations": review_report["unknown_citations"],
                    "unsupported_claim_count": len(review_report["unsupported_claims"]),
                    "missing_sections": review_report["missing_sections"],
                    "blocking_agents": revision_plan["blocking_agents"],
                }
            )
            if review_report["status"] == "accepted":
                break
            review_feedback = review_report

        (intermediate_dir / "writer_draft.md").write_text(draft, encoding="utf-8")
        self._write_json(self.output_dir / "review_report.json", review_report)
        self._write_json(self.output_dir / "revision_log.json", {"iterations": revision_log})

        if review_report["status"] == "accepted":
            final = self.polish_agent.run(draft)
        else:
            final = draft

        final_verification = self.final_verification_reviewer.review(draft, final, papers)
        if final_verification["status"] != "accepted":
            final = draft
            final_verification["final_action"] = "polish_output_rejected; accepted draft retained"
        else:
            final_verification["final_action"] = "polish_output_accepted"

        self._write_json(self.output_dir / "final_verification.json", final_verification)
        evaluation_report = self.evaluation_reflection_agent.evaluate(
            search_report,
            review_report,
            final_verification,
            revision_log,
        )
        self._write_json(self.output_dir / "evaluation_report.json", evaluation_report)
        (self.output_dir / "reflection_log.md").write_text(
            self.evaluation_reflection_agent.to_markdown(evaluation_report),
            encoding="utf-8",
        )
        (self.output_dir / "survey.md").write_text(final, encoding="utf-8")

        return {
            "status": review_report["status"]
            if final_verification["status"] == "accepted"
            else final_verification["status"],
            "survey": str(self.output_dir / "survey.md"),
            "review_report": str(self.output_dir / "review_report.json"),
            "final_verification": str(self.output_dir / "final_verification.json"),
            "evaluation_report": str(self.output_dir / "evaluation_report.json"),
        }

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")

    def _run_writer(
        self,
        search_report: dict[str, Any],
        review_feedback: dict[str, Any] | None,
    ) -> str:
        signature = inspect.signature(self.writer_agent.run)
        if "review_feedback" in signature.parameters:
            return self.writer_agent.run(search_report, review_feedback=review_feedback)
        return self.writer_agent.run(search_report)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = Orchestrator(
        corpus_path=root / "data" / "papers.json",
        output_dir=root / "outputs",
    ).run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
