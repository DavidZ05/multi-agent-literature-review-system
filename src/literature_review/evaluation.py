from __future__ import annotations

from typing import Any

from src.literature_review.api import APIResponseError, load_prompt
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
        evidence_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        writer_iteration_count = len(revision_log)
        writer_revision_count = max(0, writer_iteration_count - 1)
        if self.backend_note() == "api":
            response = self.call_api(
                load_prompt("evaluation_reflection"),
                {
                    "search_report": search_report,
                    "review_report": review_report,
                    "final_verification": final_verification,
                    "revision_log": revision_log,
                    "evidence_context": evidence_context,
                },
            )
            scores = _scores(response)
            if evidence_context is not None:
                scores["claim_source_alignment"] = min(
                    scores["claim_source_alignment"],
                    _evidence_alignment_score(evidence_context),
                )
                component_average = round(
                    sum(
                        scores[name]
                        for name in (
                            "citation_integrity",
                            "claim_source_alignment",
                            "process_control",
                            "literature_coverage",
                        )
                    )
                    / 4,
                    2,
                )
                scores["overall"] = min(scores["overall"], component_average)
            return {
                "agent": "Evaluation / Reflection Agent",
                "backend": self.backend_note(),
                "scores": scores,
                # Compatibility alias retained for consumers of pre-0.7.3 artifacts.
                "revision_iterations": writer_iteration_count,
                "writer_iteration_count": writer_iteration_count,
                "writer_revision_count": writer_revision_count,
                "records_included": search_report["records_included"],
                "final_status": final_verification["status"],
                "reflections": _string_list(response, "reflections"),
                "next_run_improvements": _string_list(
                    response,
                    "next_run_improvements",
                ),
                "evidence_status": _evidence_status(evidence_context),
            }
        citation_score = (
            5.0
            if not final_verification["unknown_citations"]
            and not final_verification.get("missing_citations", [])
            else 2.0
        )
        support_score = 5.0 if not final_verification["unsupported_claims"] else 3.0
        if evidence_context is not None:
            support_score = min(
                support_score,
                _evidence_alignment_score(evidence_context),
            )
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
            # Compatibility alias retained for consumers of pre-0.7.3 artifacts.
            "revision_iterations": writer_iteration_count,
            "writer_iteration_count": writer_iteration_count,
            "writer_revision_count": writer_revision_count,
            "records_included": search_report["records_included"],
            "final_status": final_verification["status"],
            "evidence_status": _evidence_status(evidence_context),
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
        writer_iterations = report.get(
            "writer_iteration_count",
            report.get("revision_iterations", 0),
        )
        writer_revisions = report.get(
            "writer_revision_count",
            max(0, writer_iterations - 1),
        )
        lines = [
            "# Evaluation and Reflection",
            "",
            f"Final status: `{report['final_status']}`",
            f"Records included: {report['records_included']}",
            f"Writer iterations: {writer_iterations}",
            f"Writer revisions: {writer_revisions}",
            "",
            "## Scores",
        ]
        if report.get("evidence_status") is not None:
            lines.insert(6, f"Evidence status: `{report['evidence_status']}`")
        for name, score in report["scores"].items():
            lines.append(f"- {name}: {float(score):.1f}/5.0")
        lines.extend(["", "## Reflections"])
        lines.extend(f"- {item}" for item in report["reflections"])
        lines.extend(["", "## Next Run Improvements"])
        lines.extend(f"- {item}" for item in report["next_run_improvements"])
        return "\n".join(lines) + "\n"


def _scores(response: dict[str, Any]) -> dict[str, float]:
    value = response.get("scores")
    required = [
        "citation_integrity",
        "claim_source_alignment",
        "process_control",
        "literature_coverage",
        "overall",
    ]
    if not isinstance(value, dict):
        raise _invalid_output("scores")
    scores = {}
    for key in required:
        score = value.get(key)
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise _invalid_output("scores")
        numeric = float(score)
        if not 0.0 <= numeric <= 5.0:
            raise _invalid_output("scores")
        scores[key] = round(numeric, 2)
    return scores


def _evidence_status(evidence_context: dict[str, Any] | None) -> str | None:
    if evidence_context is None:
        return None
    status = evidence_context.get("status")
    return status if isinstance(status, str) and status else "unresolved"


def _evidence_alignment_score(evidence_context: dict[str, Any]) -> float:
    status = _evidence_status(evidence_context)
    if status == "accepted_with_documented_risk":
        return 3.0
    if isinstance(status, str) and status.startswith("accepted"):
        return 5.0
    return 2.0


def _string_list(response: dict[str, Any], field: str) -> list[str]:
    value = response.get(field)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise _invalid_output(field)
    return list(value)


def _invalid_output(field: str) -> APIResponseError:
    return APIResponseError(
        f"Model-backed reflection agent returned an invalid {field} field.",
        code="invalid_agent_output",
        retryable=False,
    )
