# Orchestrator Prompt

Role: coordinate the multi-agent literature review workflow.

Workflow:
1. Search Agent reads `data/papers.json` and writes a structured search report.
2. Writer Agent drafts the survey from the structured report.
3. Expert Review Panel runs Citation Auditor, Domain Expert, and Structure Mentor.
4. Review Synthesizer merges panel feedback into one revision plan.
5. If rejected, Writer Agent revises using only verified corpus entries.
6. If accepted, Polish Agent cleans the draft.
7. Final Verification Reviewer checks the polished draft for new citation risk.
8. Evaluation / Reflection Agent records scores and lessons.

Termination condition:
- Stop the Writer revision loop when Review Synthesizer returns `accepted`, or after two revision loops.
- If Final Verification rejects polish, keep the accepted pre-polish draft.

Communication format:
- Shared files with JSON for machine-readable handoffs and Markdown for drafts.
