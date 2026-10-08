from __future__ import annotations

import re
from typing import Any

from src.literature_review.api import APIResponseError, load_prompt
from src.literature_review.base import RuntimeAwareAgent
from src.literature_review.citations import CITATION_PATTERN

__all__ = [
    "ReviewerAgent",
    "DomainExpertAgent",
    "StructureMentorAgent",
    "ReviewSynthesizerAgent",
    "FinalVerificationReviewer",
]


class ReviewerAgent(RuntimeAwareAgent):
    """Checks citation integrity and basic report structure."""

    supports_api = False
    citation_pattern = CITATION_PATTERN
    high_risk_factual_pattern = re.compile(
        r"(?:\b\d+(?:\.\d+)?%?\b|\b(?:shows?|showed|reports?|reported|"
        r"introduces?|introduced|proposes?|proposed|evaluates?|evaluated|"
        r"improves?|improved|reduces?|reduced|increases?|increased|"
        r"decreases?|decreased|demonstrates?|demonstrated|finds?|found|"
        r"outperforms?|outperformed|achieves?|achieved)\b)",
        re.IGNORECASE,
    )
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
        missing_citations = self._find_missing_citations(markdown)
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
            if not unknown
            and not missing_citations
            and not missing_sections
            and not unsupported_claims
            else "revise"
        )
        return {
            "agent": "Citation Auditor Agent",
            "backend": self.backend_note(),
            "status": status,
            "cited_keys": cited_keys,
            "unknown_citations": unknown,
            "missing_citations": missing_citations,
            "unsupported_claims": unsupported_claims,
            "missing_sections": missing_sections,
            "recommendations": self._recommendations(
                unknown,
                missing_citations,
                missing_sections,
                unsupported_claims,
            ),
        }

    def _recommendations(
        self,
        unknown: list[str],
        missing_citations: list[dict[str, str]],
        missing: list[str],
        unsupported_claims: list[dict[str, Any]],
    ) -> list[str]:
        recommendations = []
        if unknown:
            recommendations.append("Remove or replace citations not present in data/papers.json.")
        if missing_citations:
            recommendations.append(
                "Add approved citations to high-risk factual claims or remove those claims."
            )
        if missing:
            recommendations.append("Restore required survey sections before final polish.")
        if unsupported_claims:
            recommendations.append(
                "Revise claims whose wording is not aligned with the cited source metadata."
            )
        if not recommendations:
            recommendations.append("No blocking citation or structure issues found.")
        return recommendations

    def _find_missing_citations(self, markdown: str) -> list[dict[str, str]]:
        body = markdown.split("## References", 1)[0]
        section = "Preamble"
        missing: list[dict[str, str]] = []
        for raw_line in body.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("#"):
                section = stripped.lstrip("#").strip() or section
                continue
            if not stripped or set(stripped) <= {"-", "|", ":", " "}:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`*])", stripped):
                sentence = sentence.strip()
                if (
                    sentence
                    and not self.citation_pattern.search(sentence)
                    and self.high_risk_factual_pattern.search(sentence)
                ):
                    missing.append({"sentence": sentence, "section": section})
        return missing

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
            if stripped.startswith("#") or set(stripped) <= {"-", "|", ":", " "}:
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
            model_status = _status(response)
            if model_status == "revise" and not (blocking_reviews or model_must_fix):
                raise APIResponseError(
                    "Model-backed review agent returned revise without a concrete "
                    "must_fix item.",
                    code="invalid_agent_output",
                    retryable=False,
                )
            revision_required = bool(blocking_reviews) or model_status == "revise"
            blocking_agents = _dedupe(
                [review["agent"] for review in blocking_reviews]
                + (model_blocking_agents if revision_required else [])
            )
            synthesized_must_fix = must_fix + (
                model_must_fix if revision_required else []
            )
            synthesized_should_fix = should_fix + model_should_fix + (
                model_must_fix if not revision_required else []
            )
            return {
                "agent": "Review Synthesizer Agent",
                "backend": self.backend_note(),
                "status": "revise" if revision_required else "accepted",
                "blocking_agents": blocking_agents,
                "must_fix": _dedupe(synthesized_must_fix),
                "should_fix": _dedupe(synthesized_should_fix),
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
        must_fix: list[str] = []
        should_fix: list[str] = []
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

    supports_api = False
    citation_pattern = ReviewerAgent.citation_pattern

    def review(
        self,
        accepted_draft: str,
        polished_markdown: str,
        papers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        before_sequence = self.citation_pattern.findall(accepted_draft)
        after_sequence = self.citation_pattern.findall(polished_markdown)
        before = sorted(set(before_sequence))
        after = sorted(set(after_sequence))
        new_citations = sorted(set(after) - set(before))
        removed_citations = sorted(set(before) - set(after))
        citation_sequence_changed = before_sequence != after_sequence
        citation_context_drift = _citation_context_drift(
            accepted_draft,
            polished_markdown,
            self.citation_pattern,
        )
        semantic_drift = _semantic_context_drift(
            accepted_draft,
            polished_markdown,
            self.citation_pattern,
        )
        headings_changed = _headings(accepted_draft) != _headings(polished_markdown)
        references_changed = _reference_entries(accepted_draft) != _reference_entries(
            polished_markdown
        )
        citation_audit = ReviewerAgent(self.runtime_config).review(polished_markdown, papers)
        status = "accepted"
        if (
            citation_sequence_changed
            or citation_context_drift
            or semantic_drift
            or headings_changed
            or references_changed
            or citation_audit["status"] != "accepted"
        ):
            status = "revise"
        return {
            "agent": "Final Verification Reviewer",
            "backend": self.backend_note(),
            "status": status,
            "citations_before_polish": before,
            "citations_after_polish": after,
            "new_citations_after_polish": new_citations,
            "removed_citations_after_polish": removed_citations,
            "citation_sequence_changed": citation_sequence_changed,
            "citation_context_drift": citation_context_drift,
            "semantic_drift": semantic_drift,
            "headings_changed": headings_changed,
            "references_changed": references_changed,
            "unknown_citations": citation_audit["unknown_citations"],
            "missing_citations": citation_audit["missing_citations"],
            "unsupported_claims": citation_audit["unsupported_claims"],
            "missing_sections": citation_audit["missing_sections"],
            "recommendations": self._recommendations(
                new_citations,
                removed_citations,
                citation_sequence_changed,
                citation_context_drift,
                semantic_drift,
                headings_changed,
                references_changed,
                citation_audit,
            ),
        }

    def _recommendations(
        self,
        new_citations: list[str],
        removed_citations: list[str],
        citation_sequence_changed: bool,
        citation_context_drift: list[dict[str, Any]],
        semantic_drift: list[dict[str, Any]],
        headings_changed: bool,
        references_changed: bool,
        citation_audit: dict[str, Any],
    ) -> list[str]:
        recommendations = []
        if new_citations:
            recommendations.append("Reject polish output or re-run Writer review; polish added citations.")
        if removed_citations:
            recommendations.append(
                "Reject polish output or re-run Writer review; polish removed citations."
            )
        if citation_sequence_changed and not (new_citations or removed_citations):
            recommendations.append(
                "Reject polish output; citation occurrence count or order changed."
            )
        if citation_context_drift:
            recommendations.append(
                "Reject polish output; one or more citations moved away from their accepted claim context."
            )
        if semantic_drift:
            recommendations.append(
                "Reject polish output; a protected factual anchor changed meaning."
            )
        if headings_changed:
            recommendations.append("Reject polish output; the accepted heading structure changed.")
        if references_changed:
            recommendations.append("Reject polish output; reference entries changed.")
        audit_recommendations = citation_audit.get("recommendations", [])
        if recommendations:
            audit_recommendations = [
                recommendation
                for recommendation in audit_recommendations
                if recommendation != "No blocking citation or structure issues found."
            ]
        recommendations.extend(audit_recommendations)
        if not recommendations:
            recommendations.append(
                "Final polish preserved accepted structure, references, and citation context."
            )
        return recommendations


def _headings(markdown: str) -> list[str]:
    return [line.strip() for line in markdown.splitlines() if line.lstrip().startswith("#")]


def _reference_entries(markdown: str) -> list[str]:
    if "## References" not in markdown:
        return []
    references = markdown.split("## References", 1)[1]
    return [line.strip() for line in references.splitlines() if line.strip()]


def _citation_context_drift(
    before_markdown: str,
    after_markdown: str,
    pattern: re.Pattern[str],
) -> list[dict[str, Any]]:
    before = _citation_contexts(before_markdown, pattern)
    after = _citation_contexts(after_markdown, pattern)
    if [item[0] for item in before] != [item[0] for item in after]:
        return []
    drift = []
    for index, ((key, old_context), (_, new_context)) in enumerate(zip(before, after)):
        old_tokens = _context_tokens(old_context, pattern)
        new_tokens = _context_tokens(new_context, pattern)
        union = old_tokens | new_tokens
        similarity = 1.0 if not union else len(old_tokens & new_tokens) / len(union)
        if similarity < 0.35:
            drift.append(
                {
                    "occurrence": index + 1,
                    "citation_key": key,
                    "similarity": round(similarity, 3),
                }
            )
    return drift


def _citation_contexts(
    markdown: str,
    pattern: re.Pattern[str],
) -> list[tuple[str, str]]:
    contexts = []
    for line in markdown.splitlines():
        for key in pattern.findall(line):
            contexts.append((key, line.strip()))
    return contexts


def _context_tokens(text: str, pattern: re.Pattern[str]) -> set[str]:
    without_citations = pattern.sub("", text.lower())
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9-]*", without_citations)
        if len(token) >= 3
    }


_NEGATION = re.compile(
    r"\b(?:no|not|never|neither|nor|without|fail(?:s|ed|ing)?|"
    r"cannot|can't|doesn't|don't|didn't|isn't|aren't|wasn't|weren't)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:%|\s*(?:ms|s|mb|gb|kb))?",
    re.IGNORECASE,
)
_DIRECTION_GROUPS = {
    "increase": re.compile(
        r"\b(?:increase[sd]?|improve[sd]?|higher|rise[sn]?|grow(?:s|th)?|"
        r"outperform(?:s|ed)?)\b",
        re.IGNORECASE,
    ),
    "decrease": re.compile(
        r"\b(?:decrease[sd]?|reduce[sd]?|lower|decline[sd]?|drop[sp]?|"
        r"degrade[sd]?|underperform(?:s|ed)?)\b",
        re.IGNORECASE,
    ),
}
_MODAL_GROUPS = {
    "possible": re.compile(
        r"\b(?:may|might|could|can|possibly|potentially)\b",
        re.IGNORECASE,
    ),
    "probable": re.compile(
        r"\b(?:likely|probably|generally|typically)\b",
        re.IGNORECASE,
    ),
    "certain": re.compile(
        r"\b(?:must|will|always|never|proves?|demonstrates?)\b",
        re.IGNORECASE,
    ),
}
_COMPARISON = re.compile(
    r"\b(?:more|less|fewer|better|worse|equal|at least|at most|"
    r"greater than|less than)\b|[<>]=?",
    re.IGNORECASE,
)
_NAMED_ANCHOR = re.compile(
    r"\b(?:[A-Z]{2,}[A-Z0-9-]*|[A-Za-z]+-\d+(?:\.\d+)*|"
    r"[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)+)\b"
)


def _semantic_context_drift(
    before_markdown: str,
    after_markdown: str,
    pattern: re.Pattern[str],
) -> list[dict[str, Any]]:
    before = _citation_contexts(before_markdown, pattern)
    after = _citation_contexts(after_markdown, pattern)
    if [item[0] for item in before] != [item[0] for item in after]:
        return []
    drift: list[dict[str, Any]] = []
    for index, ((key, old_context), (_, new_context)) in enumerate(
        zip(before, after)
    ):
        old_signature = _semantic_signature(old_context, pattern)
        new_signature = _semantic_signature(new_context, pattern)
        changed = [
            field
            for field in old_signature
            if old_signature[field] != new_signature[field]
        ]
        if changed:
            drift.append(
                {
                    "occurrence": index + 1,
                    "citation_key": key,
                    "changed_anchors": changed,
                    "before": {field: old_signature[field] for field in changed},
                    "after": {field: new_signature[field] for field in changed},
                }
            )
    return drift


def _semantic_signature(
    text: str,
    pattern: re.Pattern[str],
) -> dict[str, list[str]]:
    content = pattern.sub("", text)
    return {
        "negation": sorted(
            match.group(0).lower() for match in _NEGATION.finditer(content)
        ),
        "numbers": sorted(
            " ".join(match.group(0).lower().split())
            for match in _NUMBER.finditer(content)
        ),
        "direction": sorted(
            name
            for name, expression in _DIRECTION_GROUPS.items()
            if expression.search(content)
        ),
        "modality": sorted(
            name
            for name, expression in _MODAL_GROUPS.items()
            if expression.search(content)
        ),
        "comparison": sorted(
            match.group(0).lower() for match in _COMPARISON.finditer(content)
        ),
        "named_entities": sorted(set(_NAMED_ANCHOR.findall(content))),
    }


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
