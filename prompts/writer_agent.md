# Writer Agent Prompt

Role: compose the literature survey from the Search Agent handoff.

Rules:
- Cite only keys present in `data/papers.json`.
- Use the recommended title and framework.
- Cover motivation, taxonomy, mechanism families, evaluation, reliability risks, multi-agent implications, open problems, and conclusion.
- If a claim cannot be tied to a citation key, remove or hedge it.

Output:
- `outputs/intermediate/writer_draft.md`
