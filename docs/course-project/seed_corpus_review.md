# Seed Corpus Review

> Archive notice: this review records the seed corpus used for the original
> course submission. Current runs may extend that corpus through the human
> approval workflow described in the root `README.md`.

This document records the additional seed-paper review performed before expanding `data/papers.json`.

## Inclusion Criteria

Papers were added only if they met all conditions below:

1. The paper has a stable arXiv page or similarly stable source.
2. The paper directly improves the project scope: LLM agent memory mechanisms, memory evaluation, memory reliability, or multi-agent orchestration.
3. The paper fills a coverage gap in the existing corpus rather than duplicating an already covered theme.
4. The paper can be summarized as a concrete design or evaluation contribution.

## Added Papers

| Citation key | Source | Reason for inclusion |
|---|---|---|
| `xu2025amem` | https://arxiv.org/abs/2502.12110 | Adds dynamic memory organization through Zettelkasten-style indexing, linking, and memory evolution. |
| `hu2025memoryagentbench` | https://arxiv.org/abs/2507.05257 | Adds an incremental multi-turn memory benchmark covering retrieval, test-time learning, long-range understanding, and selective forgetting. |
| `chhikara2025mem0` | https://arxiv.org/abs/2504.19413 | Adds production-oriented long-term memory with extraction, consolidation, retrieval, and graph-memory variants. |
| `li2025memos` | https://arxiv.org/abs/2505.22101 | Adds memory lifecycle governance and the idea of memory as a first-class operational resource. |
| `hong2023metagpt` | https://arxiv.org/abs/2308.00352 | Adds a multi-agent orchestration reference about SOPs, role specialization, and cascading hallucination reduction. |

## Reviewed but Not Added

| Paper | Reason for exclusion |
|---|---|
| AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation | Useful multi-agent framework background, but less directly tied to memory and less specific to the project's SOP-style pipeline than MetaGPT. |
| ReAct: Synergizing Reasoning and Acting in Language Models | Foundational agent reasoning/action paper, but the current survey is about memory-augmented agents rather than general agent prompting. |

## Coverage Impact

The original corpus already covered early memory mechanisms, reflection, social/embodied agents, and long-term memory benchmarks. The added papers improve coverage in five areas:

- dynamic memory organization;
- production-grade long-term memory;
- memory lifecycle governance;
- incremental multi-turn memory evaluation;
- multi-agent workflow reliability.
