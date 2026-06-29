from __future__ import annotations

from typing import Any

from src.literature_review.base import RuntimeAwareAgent

__all__ = ["EvaluationReflectionAgent"]


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
