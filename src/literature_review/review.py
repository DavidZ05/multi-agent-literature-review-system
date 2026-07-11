from __future__ import annotations

import re
from typing import Any

from src.literature_review.api import APIResponseError, load_prompt
from src.literature_review.base import RuntimeAwareAgent

__all__ = [
    "ReviewerAgent",
    "DomainExpertAgent",
    "StructureMentorAgent",
    "ReviewSynthesizerAgent",
    "FinalVerificationReviewer",
]


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
        if self.backend_note() == "api":
            response = self.call_api(
                load_prompt("domain_expert"),
                {
                    "markdown": markdown,
                    "papers": papers,
                    "search_report": search_report,
                    "categories_reviewed": categories,
                },
            )
            return {
                "agent": "Domain Expert Agent",
                "backend": self.backend_note(),
                "status": _status(response),
                "review_focus": "memory-agent literature coverage and academic framing",
                "paper_count_reviewed": len(papers),
                "categories_reviewed": categories,
                "coverage": _dict_field(response, "coverage"),
                "missing_or_weak_areas": _string_list(response, "missing_or_weak_areas"),
                "recommendations": _string_list(response, "recommendations"),
            }
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
        if self.backend_note() == "api":
            response = self.call_api(
                load_prompt("structure_mentor"),
                {
                    "markdown": markdown,
                    "expected_headings": self.expected_headings,
                },
            )
            return {
                "agent": "Structure Mentor Agent",
                "backend": self.backend_note(),
                "status": _status(response),
                "word_count": _int_field(response, "word_count"),
                "missing_headings": _string_list(response, "missing_headings"),
                "recommendations": _string_list(response, "recommendations"),
            }
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
        blocking_reviews, must_fix, should_fix = self._deterministic_findings(reviews)
        if self.backend_note() == "api":
            response = self.call_api(
                load_prompt("review_synthesizer"),
                {"reviews": reviews},
            )
            model_must_fix = _string_list(response, "must_fix")
            model_should_fix = _string_list(response, "should_fix")
            model_blocking_agents = _string_list(response, "blocking_agents")
            blocking_agents = _dedupe(
                [review["agent"] for review in blocking_reviews]
                + model_blocking_agents
            )
            return {
                "agent": "Review Synthesizer Agent",
                "backend": self.backend_note(),
                "status": "revise" if blocking_reviews else _status(response),
                "blocking_agents": blocking_agents,
                "must_fix": _dedupe(must_fix + model_must_fix),
                "should_fix": _dedupe(should_fix + model_should_fix),
                "iteration_stop_rule": _string_field(
                    response,
                    "iteration_stop_rule",
                ),
            }
        return self._deterministic_report(reviews)

    def _deterministic_findings(
        self,
        reviews: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
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
        return blocking_reviews, must_fix, should_fix

    def _deterministic_report(self, reviews: list[dict[str, Any]]) -> dict[str, Any]:
        blocking_reviews, must_fix, should_fix = self._deterministic_findings(reviews)
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
        if new_citations or removed_citations or citation_audit["status"] != "accepted":
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
            "recommendations": self._recommendations(
                new_citations,
                removed_citations,
                citation_audit,
            ),
        }

    def _recommendations(
        self,
        new_citations: list[str],
        removed_citations: list[str],
        citation_audit: dict[str, Any],
    ) -> list[str]:
        recommendations = []
        if new_citations:
            recommendations.append("Reject polish output or re-run Writer review; polish added citations.")
        if removed_citations:
            recommendations.append(
                "Reject polish output or re-run Writer review; polish removed citations."
            )
        recommendations.extend(citation_audit.get("recommendations", []))
        if not recommendations:
            recommendations.append("Final polish preserved the accepted citation set.")
        return recommendations


def _status(response: dict[str, Any]) -> str:
    status = response.get("status")
    if status not in {"accepted", "advisory", "revise"}:
        raise APIResponseError(
            "Model-backed review agent returned an invalid status.",
            code="invalid_agent_output",
            retryable=False,
        )
    return status


def _string_field(response: dict[str, Any], field: str) -> str:
    value = response.get(field)
    if not isinstance(value, str) or not value.strip():
        raise APIResponseError(
            f"Model-backed review agent returned an invalid {field} field.",
            code="invalid_agent_output",
            retryable=False,
        )
    return value


def _int_field(response: dict[str, Any], field: str) -> int:
    value = response.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIResponseError(
            f"Model-backed review agent returned an invalid {field} field.",
            code="invalid_agent_output",
            retryable=False,
        )
    return value


def _dict_field(response: dict[str, Any], field: str) -> dict[str, Any]:
    value = response.get(field)
    if not isinstance(value, dict):
        raise APIResponseError(
            f"Model-backed review agent returned an invalid {field} field.",
            code="invalid_agent_output",
            retryable=False,
        )
    return value


def _string_list(response: dict[str, Any], field: str) -> list[str]:
    value = response.get(field)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise APIResponseError(
            f"Model-backed review agent returned an invalid {field} field.",
            code="invalid_agent_output",
            retryable=False,
        )
    return list(value)


def _dedupe(items: list[str]) -> list[str]:
    output = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
