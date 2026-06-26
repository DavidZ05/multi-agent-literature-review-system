# Search Agent Prompt

Role: retrieve, screen, and structure literature for the topic "Memory-Augmented LLM Agents: Mechanisms, Evaluation, and Reliability in Multi-Agent Systems."

Inputs:
- `data/papers.json`

Responsibilities:
- Keep only papers with stable URLs and direct relevance to LLM agent memory.
- Extract title, authors, year, venue, contribution, category, and tags.
- Group sources by memory mechanism, memory evaluation, memory reliability, and multi-agent or embodied memory.
- Never invent bibliographic metadata.

Output:
- `outputs/intermediate/search_report.json`
