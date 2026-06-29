from __future__ import annotations

import re
from typing import Any

from src.literature_review.base import RuntimeAwareAgent
from src.literature_review.corpus import (
    PROJECT_TITLE,
    citation_label,
    first_author_last_name,
)

__all__ = ["PolishAgent", "WriterAgent"]


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


class PolishAgent(RuntimeAwareAgent):
    """Applies final mechanical cleanup without adding new claims."""

    def run(self, markdown: str) -> str:
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        markdown = markdown.replace("  ", " ")
        return markdown.strip() + "\n"
