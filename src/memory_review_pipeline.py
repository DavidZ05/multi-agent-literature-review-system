from __future__ import annotations

import os
import json
import inspect
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from src.literature_review.corpus import (
    PROJECT_TITLE,
    citation_label,
    first_author_last_name,
    load_papers,
)


@dataclass(frozen=True)
class AgentAPISettings:
    """Resolved API settings for one agent."""

    agent_id: str
    backend: str = "deterministic"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60

    @property
    def api_enabled(self) -> bool:
        return (
            self.backend == "api"
            and bool(self.api_base_url)
            and bool(self.api_key)
            and bool(self.model)
        )

    @property
    def active_backend(self) -> str:
        if self.api_enabled:
            return "api"
        return "deterministic"

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "<configured>" if self.api_key else ""
        data["api_enabled"] = self.api_enabled
        data["active_backend"] = self.active_backend
        return data


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Shared runtime switch for deterministic agents and future API-backed agents."""

    backend: str = "deterministic"
    api_mode: str = "single"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60
    agent_overrides: dict[str, dict[str, Any]] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentRuntimeConfig":
        values = os.environ if env is None else env

        def float_value(name: str, default: float) -> float:
            try:
                return float(values.get(name, default))
            except (TypeError, ValueError):
                return default

        def int_value(name: str, default: int) -> int:
            try:
                return int(values.get(name, default))
            except (TypeError, ValueError):
                return default

        backend = values.get("AGENT_BACKEND", "deterministic").strip().lower()
        if backend not in {"deterministic", "api"}:
            backend = "deterministic"
        api_mode = values.get("AGENT_API_MODE", "single").strip().lower()
        if api_mode not in {"single", "multi"}:
            api_mode = "single"
        return cls(
            backend=backend,
            api_mode=api_mode,
            api_base_url=values.get("AGENT_API_BASE_URL", "").strip(),
            api_key=values.get("AGENT_API_KEY", "").strip(),
            model=values.get("AGENT_MODEL", "").strip(),
            temperature=float_value("AGENT_TEMPERATURE", 0.2),
            timeout_seconds=int_value("AGENT_TIMEOUT_SECONDS", 60),
            agent_overrides=cls._agent_overrides(values),
        )

    @classmethod
    def _agent_overrides(cls, values: Mapping[str, str]) -> dict[str, dict[str, Any]]:
        agent_ids = [
            "search",
            "writer",
            "reviewer",
            "domain_expert",
            "structure_mentor",
            "review_synthesizer",
            "polish",
            "final_verification",
            "evaluation_reflection",
        ]
        overrides: dict[str, dict[str, Any]] = {}
        for agent_id in agent_ids:
            prefix = f"{agent_id.upper()}_AGENT_"
            raw_values = {
                "api_base_url": values.get(f"{prefix}API_BASE_URL", "").strip(),
                "api_key": values.get(f"{prefix}API_KEY", "").strip(),
                "model": values.get(f"{prefix}MODEL", "").strip(),
                "temperature": values.get(f"{prefix}TEMPERATURE", "").strip(),
                "timeout_seconds": values.get(f"{prefix}TIMEOUT_SECONDS", "").strip(),
            }
            cleaned = {
                key: value
                for key, value in raw_values.items()
                if value != ""
            }
            if cleaned:
                overrides[agent_id] = cleaned
        return overrides

    @property
    def api_enabled(self) -> bool:
        return self.default_settings().api_enabled

    @property
    def active_backend(self) -> str:
        return self.default_settings().active_backend

    def default_settings(self) -> AgentAPISettings:
        return AgentAPISettings(
            agent_id="default",
            backend=self.backend,
            api_base_url=self.api_base_url,
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )

    def for_agent(self, agent_id: str) -> AgentAPISettings:
        default = self.default_settings()
        if self.api_mode != "multi":
            return AgentAPISettings(agent_id=agent_id, **{
                "backend": default.backend,
                "api_base_url": default.api_base_url,
                "api_key": default.api_key,
                "model": default.model,
                "temperature": default.temperature,
                "timeout_seconds": default.timeout_seconds,
            })

        overrides = (self.agent_overrides or {}).get(agent_id, {})
        return AgentAPISettings(
            agent_id=agent_id,
            backend=self.backend,
            api_base_url=overrides.get("api_base_url", self.api_base_url),
            api_key=overrides.get("api_key", self.api_key),
            model=overrides.get("model", self.model),
            temperature=self._coerce_float(
                overrides.get("temperature", self.temperature),
                self.temperature,
            ),
            timeout_seconds=self._coerce_int(
                overrides.get("timeout_seconds", self.timeout_seconds),
                self.timeout_seconds,
            ),
        )

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "<configured>" if self.api_key else ""
        data["api_enabled"] = self.api_enabled
        data["active_backend"] = self.active_backend
        data["agent_overrides"] = {
            agent_id: self._sanitized_agent_override(agent_id)
            for agent_id in sorted((self.agent_overrides or {}).keys())
        }
        data["agent_settings"] = {
            agent_id: self.for_agent(agent_id).public_dict()
            for agent_id in [
                "search",
                "writer",
                "reviewer",
                "domain_expert",
                "structure_mentor",
                "review_synthesizer",
                "polish",
                "final_verification",
                "evaluation_reflection",
            ]
        }
        return data

    def _sanitized_agent_override(self, agent_id: str) -> dict[str, Any]:
        override = dict((self.agent_overrides or {}).get(agent_id, {}))
        if override.get("api_key"):
            override["api_key"] = "<configured>"
        return override

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


class RuntimeAwareAgent:
    """Common base for agents that may later swap deterministic logic for API calls."""

    def __init__(self, runtime_config: AgentRuntimeConfig | None = None) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.agent_id = self._agent_id_from_class_name()

    def backend_note(self) -> str:
        if self.runtime_config.for_agent(self.agent_id).api_enabled:
            return "api"
        return "deterministic-fallback"

    def _agent_id_from_class_name(self) -> str:
        name = self.__class__.__name__
        mapping = {
            "SearchAgent": "search",
            "WriterAgent": "writer",
            "ReviewerAgent": "reviewer",
            "DomainExpertAgent": "domain_expert",
            "StructureMentorAgent": "structure_mentor",
            "ReviewSynthesizerAgent": "review_synthesizer",
            "PolishAgent": "polish",
            "FinalVerificationReviewer": "final_verification",
            "EvaluationReflectionAgent": "evaluation_reflection",
        }
        return mapping.get(name, name.lower())


class SearchAgent(RuntimeAwareAgent):
    """Selects and groups papers from the verified corpus."""

    def run(self, papers: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for paper in papers:
            grouped[paper["category"]].append(paper)

        for category in grouped:
            grouped[category].sort(key=lambda item: (item["year"], item["title"]))

        return {
            "agent": "Search Agent",
            "backend": self.backend_note(),
            "query": PROJECT_TITLE,
            "date": date.today().isoformat(),
            "records_identified": len(papers),
            "records_included": len(papers),
            "inclusion_criteria": [
                "Directly addresses LLM agent memory mechanisms, management, or evaluation.",
                "Provides a reusable design pattern, benchmark, or empirical finding.",
                "Has a stable arXiv or publisher URL for reference verification.",
            ],
            "grouped_papers": grouped,
        }


class WriterAgent(RuntimeAwareAgent):
    """Composes a survey draft from the Search Agent handoff."""

    def run(
        self,
        search_report: dict[str, Any],
        review_feedback: dict[str, Any] | None = None,
    ) -> str:
        grouped = search_report["grouped_papers"]
        all_papers = [
            paper
            for papers in grouped.values()
            for paper in papers
        ]
        self._fallback_papers = all_papers

        mechanism_papers = grouped.get("memory mechanism", [])
        evaluation_papers = grouped.get("memory evaluation", [])
        reliability_papers = grouped.get("memory reliability", [])
        multi_agent_papers = grouped.get("multi-agent and embodied memory", [])
        orchestration_papers = grouped.get("multi-agent orchestration", [])

        sections = [
            f"# {PROJECT_TITLE}",
            "",
            "## Abstract",
            (
                "LLM agents become useful over long horizons only when they can preserve, "
                "organize, retrieve, and revise information beyond a single context window. "
                "This survey reviews memory-augmented LLM agents through three linked "
                "questions: what memory mechanisms are used, how they are evaluated, and "
                "what reliability risks appear when memory is deployed in multi-agent "
                "systems. The reviewed literature suggests that agent memory is best "
                "understood as a write-manage-read control loop rather than a passive "
                "database. Retrieval stores, reflection buffers, hierarchical virtual "
                "context, skill libraries, and learned or rule-based forgetting policies "
                "offer complementary benefits. However, the same mechanisms that improve "
                "continuity can also preserve mistakes, replay stale experience, and spread "
                "incorrect facts across agents. For multi-agent literature-review systems, "
                "the safest design is therefore not maximum memory, but verified memory: "
                "shared artifacts should carry citation keys, source URLs, confidence "
                "labels, and reviewer decisions."
            ),
            "",
            "## 1. Introduction",
            (
                "A stateless language model can answer a prompt, but an agent must act "
                "across time. It observes new information, chooses actions, receives "
                "feedback, and should avoid repeating old mistakes. Memory is the component "
                "that connects these episodes. Recent surveys frame memory as a core "
                "capability for autonomous LLM agents, not as a convenience feature "
                f"({self._cite_any(mechanism_papers, 'du2026memory')}; "
                f"{self._cite_any(mechanism_papers, 'zhang2024survey')}). "
                "The problem is especially visible in multi-agent systems: one agent may "
                "retrieve papers, another writes, and another checks claims. Unless their "
                "intermediate artifacts are persistent and verifiable, later agents inherit "
                "untraceable claims."
            ),
            "",
            "The research question guiding this survey is: **How do memory mechanisms improve "
            "the reliability, continuity, and coordination of LLM-based multi-agent systems?**",
            "",
            "## 2. Methodology",
            (
                "This survey uses a corpus-first narrative review method. The Search Agent "
                "starts from a verified set of papers stored in `data/papers.json`, where "
                "each record contains a citation key, bibliographic metadata, URL, topic "
                "category, and contribution note. The inclusion criteria are deliberately "
                "narrow: a paper must address memory mechanisms, memory evaluation, memory "
                "management, or memory-dependent behavior in LLM agents. General LLM papers "
                "are excluded unless they directly inform agent memory design. The Writer "
                "Agent then organizes the evidence by mechanism family rather than by "
                "chronology, because the goal is to compare design choices that a builder "
                "of a multi-agent system must make."
            ),
            (
                "The method is not a full systematic review. It does not claim exhaustive "
                "coverage of every paper on agent memory, and it does not perform meta-analysis. "
                "Instead, it prioritizes traceability and reproducibility. Every cited claim "
                "must be tied to a citation key in the corpus, and the final reference list is "
                "generated from that corpus. This makes the survey suitable for the course "
                "project: the system demonstrates automated research, drafting, review, and "
                "polish while keeping citation hallucination inspectable."
            ),
            "",
            "## 3. Taxonomy of Agent Memory",
            (
                "The literature converges on three useful axes. First, memory differs by "
                "temporal scope: short-term context, episodic traces, long-term user or task "
                "facts, and procedural skills. Second, memory differs by representation: raw "
                "conversation logs, summarized facts, vector embeddings, structured files, "
                "or executable code. Third, memory differs by control policy: always write, "
                "selectively write, consolidate, forget, or retrieve conditionally. "
                f"{self._cite_any(mechanism_papers, 'packer2023memgpt')} models memory as "
                "a virtual context hierarchy, while "
                f"{self._cite_any(mechanism_papers, 'zhong2023memorybank')} emphasizes "
                "long-term personal memory and forgetting-inspired updates. "
                f"{self._cite_any(mechanism_papers, 'xu2025amem')} adds a more dynamic "
                "view in which memories are indexed, linked, and evolved as an organized "
                "knowledge network."
            ),
            (
                "A fourth axis is ownership. In a single-agent assistant, memory often belongs "
                "to one user-agent relationship. In a multi-agent system, memory can be private "
                "to an agent, shared across a team, or published as a reviewed artifact. Private "
                "memory helps specialization: a Search Agent remembers query expansions and "
                "screening rules, while a Reviewer Agent remembers citation-risk patterns. Shared "
                "memory supports coordination, but it also raises the danger of contaminating all "
                "agents with one mistaken record. Reviewed memory is slower, but safer: only "
                "claims that pass verification become part of the common workspace."
            ),
            "",
            self._paper_table(all_papers),
            "",
            "### Mechanism Comparison",
            "",
            "| Mechanism family | Typical representation | Main strength | Main risk | Best fit in this project |",
            "|---|---|---|---|---|",
            "| Retrieval-augmented store | chunks, summaries, embeddings | broad factual recall | irrelevant or stale retrieval | Search Agent paper notes |",
            "| Reflective memory | verbal lessons and episode summaries | learns from feedback without fine-tuning | self-reinforced mistakes | Reviewer feedback loop |",
            "| Hierarchical virtual context | active context plus archival memory | handles long tasks under context limits | wrong paging decisions | long paper and notes management |",
            "| Procedural memory | executable skills or reusable routines | transfers successful behavior | brittle routines under distribution shift | citation-check and drafting routines |",
            "| Managed forgetting | deletion, consolidation, or decay policy | controls memory growth and noise | deleting useful rare evidence | corpus pruning and source updates |",
            "| Agentic memory network | linked notes, tags, and evolving relations | adapts memory organization over time | harder auditability if links are opaque | paper relation memory |",
            "| Memory operating system | governed memory resources and lifecycle controls | traceability and cross-context governance | infrastructure complexity | provenance and deletion policies |",
            "",
            "## 4. Mechanism Families",
            "",
            "### 4.1 Retrieval-Augmented Memory Stores",
            (
                "The most common pattern stores past interactions or extracted facts in an "
                "external database and retrieves relevant items at inference time. This "
                "pattern is simple, modular, and compatible with existing RAG systems. Its "
                "weakness is that similarity is not the same as usefulness: a retrieved "
                "memory can be outdated, misleading, or over-specific."
            ),
            (
                "For literature review agents, retrieval memory should not store unstructured "
                "snippets alone. A useful record should include title, authors, year, URL, "
                "abstract-level contribution, tags, and a local citation key. This shifts the "
                "memory unit from a vague text chunk to an inspectable research object. The "
                "Search Agent in this project follows that pattern by writing structured JSON "
                "rather than handing the Writer Agent a loose note dump."
            ),
            (
                f"{self._cite_any(mechanism_papers, 'chhikara2025mem0')} is useful here "
                "because it treats long-term conversational memory as a production problem: "
                "the system must extract, consolidate, and retrieve salient information while "
                "controlling latency and token cost. For a literature-review agent, the same "
                "principle applies to paper notes: storing everything is less useful than "
                "preserving compact, retrievable, source-grounded facts."
            ),
            "",
            "### 4.2 Reflective and Episodic Memory",
            (
                "Reflection-based agents convert feedback into verbal lessons. "
                f"{self._cite_any(mechanism_papers, 'shinn2023reflexion')} stores reflections "
                "in an episodic buffer so later trials can reuse lessons without weight "
                "updates. In social simulations, "
                f"{self._cite_any(multi_agent_papers, 'park2023generative')} combines "
                "observation, reflection, and planning so agents can form higher-level "
                "memories that affect future behavior. These systems show that memory is "
                "not merely recall; it is also abstraction."
            ),
            (
                "The key design issue is when reflection should be trusted. A reflection is "
                "not automatically true; it is an interpretation of an episode. In this project, "
                "Reviewer feedback is treated as higher-trust reflective memory because it is "
                "grounded in explicit checks: unknown citation keys, missing sections, and "
                "unsupported claims. By contrast, a Writer Agent's self-summary would be lower "
                "trust unless the Reviewer accepts it."
            ),
            "",
            "### 4.3 Hierarchical Virtual Context",
            (
                "Long-context models reduce pressure on external memory, but they do not "
                "remove the need to manage attention. "
                f"{self._cite_any(mechanism_papers, 'packer2023memgpt')} draws an operating "
                "system analogy: limited context acts like fast memory, while archival "
                "storage acts like slower memory. The agent must decide what to page into "
                "the active context and what to keep outside it. This pattern is valuable "
                "for literature-review agents because full papers, notes, and citation "
                "audit trails cannot all fit in every prompt."
            ),
            (
                "The operating-system analogy is especially useful for multi-agent systems. "
                "Agents should not all receive the same oversized context. The Search Agent "
                "needs bibliographic records; the Writer Agent needs screened contributions; "
                "the Reviewer Agent needs the draft plus source keys; the Polish Agent needs "
                "only the accepted draft and a rule forbidding new claims. Hierarchical memory "
                "therefore supports role-specific context rather than maximal context."
            ),
            "",
            "### 4.4 Procedural and Skill Memory",
            (
                "Some agents remember not only facts, but procedures. "
                f"{self._cite_any(multi_agent_papers, 'wang2023voyager')} uses an expanding "
                "skill library of executable code, allowing the agent to reuse successful "
                "behaviors in new Minecraft worlds. For research systems, the analogous "
                "memory is a library of search strategies, screening rules, citation-check "
                "routines, and reviewer rubrics."
            ),
            (
                "Procedural memory matters because a literature review is a repeated workflow, "
                "not a single answer. The same system can be reused for another topic by replacing "
                "the corpus and keeping the orchestration logic. This is why the project separates "
                "`data/`, `prompts/`, `src/`, and `outputs/`: the memory of how to conduct the "
                "review is encoded in prompts and code, while the memory of what was reviewed is "
                "stored in the corpus and intermediate artifacts."
            ),
            "",
            "### 4.5 Memory Management and Forgetting",
            (
                "A naive memory system grows forever. The reliability literature shows why that "
                "is dangerous: old records may be similar enough to retrieve but wrong for the "
                "current task. "
                f"{self._cite_any(reliability_papers, 'xiong2025memory')} emphasizes that "
                "addition and deletion policies shape long-term agent behavior. For survey "
                "generation, this implies that memory management should include source aging, "
                "duplicate detection, correction logs, and explicit removal of failed citations. "
                "Forgetting is not the opposite of intelligence; it is part of maintaining a "
                "usable evidence base."
            ),
            "",
            "### 4.6 Dynamic Organization and Memory Governance",
            (
                f"{self._cite_any(mechanism_papers, 'xu2025amem')} pushes memory beyond "
                "flat storage by organizing notes through dynamic indexing, linking, and "
                "memory evolution. This is important for research agents because papers are "
                "not isolated facts: they relate through shared benchmarks, mechanisms, risks, "
                "and evaluation assumptions. "
                f"{self._cite_any(reliability_papers, 'li2025memos')} complements this view "
                "by treating memory as an operational resource that needs lifecycle governance, "
                "traceable access, and controllable migration across memory types."
            ),
            "",
            "## 5. Evaluation",
            (
                "Evaluation has moved from simple recall toward long-horizon interaction. "
                f"{self._cite_any(evaluation_papers, 'maharana2024locomo')} evaluates "
                "very long-term conversational memory across sessions. "
                f"{self._cite_any(evaluation_papers, 'wu2024longmemeval')} tests information "
                "extraction, multi-session reasoning, temporal reasoning, knowledge updates, "
                "and abstention. Newer work such as "
                f"{self._cite_any(evaluation_papers, 'hu2025memoryagentbench')}, "
                f"{self._cite_any(evaluation_papers, 'shutova2026structmemeval')} and "
                f"{self._cite_any(evaluation_papers, 'wu2026longmemevalv2')} shifts the "
                "focus toward structured memory and environment-specific experience. The "
                "trend is clear: a good memory system should retrieve compact evidence, "
                "track time, update stale facts, and know when memory is insufficient."
            ),
            (
                "Five evaluation abilities are especially relevant for multi-agent literature "
                "review. The first is factual recall: can the system recover the correct paper "
                "for a claim? The second is temporal reasoning: can it distinguish older mechanisms "
                "from newer benchmarks and avoid calling a 2023 method a response to a 2026 paper? "
                "The third is update handling: can it replace a weak or stale memory with a better "
                "one? The fourth is abstention: can it refuse to cite a source that is not in the "
                "verified corpus? The fifth is structural organization: can it store memory in a "
                "form that downstream agents can consume? Benchmarks such as LongMemEval and "
                "MemoryAgentBench are useful because they test memory as a working capability "
                "rather than as decorative context."
            ),
            "",
            "| Evaluation dimension | What it checks | Project proxy |",
            "|---|---|---|",
            "| Citation recall | whether cited papers exist in memory | Reviewer `unknown_citations` list |",
            "| Temporal consistency | whether claims respect publication order | corpus year fields |",
            "| Update handling | whether corrections can replace draft claims | Reviewer-Writer loop |",
            "| Abstention | whether unsupported claims are blocked | citation-key restriction |",
            "| Structural memory | whether handoffs are machine-readable | JSON intermediate artifacts |",
            "",
            "## 6. Reliability Risks",
            (
                "Memory can make agents more reliable, but it can also make errors durable. "
                f"{self._cite_any(reliability_papers, 'xiong2025memory')} reports an "
                "experience-following property: agents often produce outputs similar to "
                "retrieved experience records. This creates two risks for multi-agent "
                "systems. First, an incorrect memory can be reused by multiple downstream "
                "agents. Second, outdated experience can be replayed in a new context where "
                "it no longer applies. A literature-review system must therefore treat "
                "memory writes as evidence-bearing operations, not as casual notes."
            ),
            (
                "The most serious failure mode is not an isolated hallucination; it is a "
                "hallucination that becomes memory. Once a false reference enters a shared "
                "workspace, the Writer may cite it, the Polish Agent may make it sound more "
                "credible, and future runs may treat it as precedent. This is why the Reviewer "
                "Agent is positioned before polishing. Polishing improves fluency, but fluency "
                "can hide weak evidence. Verification must happen before stylistic improvement."
            ),
            (
                "Another risk is memory monoculture. If every agent reads the same memory without "
                "role-specific filtering, the system becomes efficient but brittle. A better design "
                "keeps separate views: Search sees broad candidate sources, Writer sees screened "
                "notes, Reviewer sees citations and claims, and Polish sees only accepted prose. "
                "The agents coordinate through shared artifacts, but they do not all share the same "
                "prompt context."
            ),
            (
                f"{self._cite_any(orchestration_papers, 'hong2023metagpt')} is relevant even "
                "though it is not a memory paper, because it identifies cascading hallucinations "
                "as a multi-agent collaboration problem and argues for SOP-style workflows. This "
                "supports the design choice in this project: shared memory should be coupled with "
                "role specialization, explicit handoffs, and review gates."
            ),
            "",
            "## 7. Implications for Multi-Agent Literature Review Systems",
            (
                "The reviewed evidence supports a design in which each agent has a narrow "
                "role and all communication occurs through structured artifacts. The Search "
                "Agent writes a verified corpus with citation keys and URLs. The Writer "
                "Agent may cite only those keys. The Reviewer Agent parses the draft, checks "
                "that every citation key exists, and rejects unknown references. The Polish "
                "Agent can improve language but cannot introduce new claims or references. "
                "This division turns memory into a shared blackboard with provenance. It "
                "also creates a natural feedback loop: if the Reviewer finds an unsupported "
                "claim, the Writer must either cite a verified source or remove the claim."
            ),
            (
                "Human-in-the-loop checkpoints should be placed where judgment matters most. "
                "The first checkpoint is topic scoping: a human chooses the research direction "
                "and decides that agent memory is narrower and more feasible than agentic RL. "
                "The second checkpoint is seed-corpus approval: a human confirms that the core "
                "papers are on-topic. The third checkpoint occurs when Reviewer flags a citation "
                "risk; a human can decide whether to remove a claim, add a source, or rewrite the "
                "argument. The fourth checkpoint is final acceptance, where a human evaluates "
                "whether the generated survey satisfies the course assignment rather than only "
                "passing automatic checks."
            ),
            (
                "This design makes the system automated by default but not irresponsible. The "
                "agents perform repetitive operations: grouping papers, drafting, checking keys, "
                "and cleaning prose. Humans intervene at high-impact decisions: scope, source "
                "trust, unresolved evidence conflicts, and final submission. In practice, this "
                "division is more credible than claiming full autonomy, because literature review "
                "requires both mechanical traceability and scholarly judgment."
            ),
            "",
            "## 8. Open Problems",
            (
                "Open problems include learned forgetting, contradiction handling across "
                "agents, privacy governance for user memory, multimodal memory, and the "
                "interaction between reinforcement learning and memory policies. RL is best "
                "positioned here as a future direction: it may help agents learn when to "
                "write, retrieve, or delete memories, but current course-project scope is "
                "better served by deterministic verification and traceable artifacts."
            ),
            (
                "A second open problem is evaluating memory in collaborative settings. Most "
                "benchmarks measure whether one assistant remembers facts across sessions. A "
                "multi-agent benchmark should ask whether a team remembers the right things at "
                "the right abstraction level: raw evidence for Search, claims for Writer, audit "
                "rules for Reviewer, and style constraints for Polish. A third problem is privacy. "
                "If agent memory stores user preferences, paper notes, or unpublished drafts, the "
                "system needs deletion, access control, and provenance policies."
            ),
            "",
            "## 9. Conclusion",
            (
                "Memory is the bridge between one-shot prompting and durable agency. The "
                "strongest systems combine multiple memory forms: retrieval for facts, "
                "reflection for lessons, hierarchy for context management, and procedural "
                "libraries for reusable actions. For multi-agent systems, the central design "
                "principle is provenance. A memory that cannot be traced should not be used "
                "as evidence. A memory that can be traced, reviewed, and revised becomes a "
                "coordination layer for reliable collaborative agents."
            ),
            "",
            "## AI Disclosure",
            (
                "This survey was produced by a local multi-agent literature review pipeline. "
                "The pipeline used AI-assisted drafting logic, structured source memory, automatic "
                "citation-key checking, and human topic selection. All references in the final "
                "survey are drawn from `data/papers.json`; unknown citation keys are rejected by "
                "the Reviewer Agent."
            ),
            "",
            "## References",
            *self._references(all_papers),
        ]
        return "\n".join(sections) + "\n"

    def _cite_any(self, papers: list[dict[str, Any]], key: str) -> str:
        for paper in papers:
            if paper["citation_key"] == key:
                return citation_label(paper)
        for paper in getattr(self, "_fallback_papers", []):
            if paper["citation_key"] == key:
                return citation_label(paper)
        return f"[MATERIAL GAP: {key}]"

    def _paper_table(self, papers: list[dict[str, Any]]) -> str:
        rows = [
            "### Table 1",
            "Key reviewed sources and their roles in the taxonomy.",
            "",
            "| Source | Category | Contribution |",
            "|---|---|---|",
        ]
        for paper in sorted(papers, key=lambda item: (item["year"], item["citation_key"])):
            rows.append(
                f"| {citation_label(paper)} | {paper['category']} | {paper['contribution']} |"
            )
        return "\n".join(rows)

    def _references(self, papers: list[dict[str, Any]]) -> list[str]:
        refs = []
        for paper in sorted(papers, key=lambda item: (first_author_last_name(item), item["year"])):
            author_text = self._format_authors(paper["authors"])
            refs.append(
                f"- [{paper['citation_key']}] {author_text} ({paper['year']}). "
                f"{paper['title']}. *{paper['venue']}*. {paper['url']}"
            )
        return refs

    def _format_authors(self, authors: list[str]) -> str:
        if len(authors) == 1:
            return authors[0]
        if len(authors) == 2:
            return f"{authors[0]}, & {authors[1]}"
        return f"{', '.join(authors[:-1])}, & {authors[-1]}"


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


class PolishAgent(RuntimeAwareAgent):
    """Applies final mechanical cleanup without adding new claims."""

    def run(self, markdown: str) -> str:
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        markdown = markdown.replace("  ", " ")
        return markdown.strip() + "\n"


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
