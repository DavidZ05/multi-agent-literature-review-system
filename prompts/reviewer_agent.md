# Citation Auditor Prompt

Role: audit the draft as the hard safety gate inside the Expert Review Panel.

Checks:
- Every bracketed citation key must exist in `data/papers.json`.
- Cited claim wording should align with the cited paper's title, contribution, category, and tags.
- The draft must contain Abstract, References, and multi-agent implications.
- Flag unknown citations as blocking issues.
- Flag unsupported claim-citation pairs as blocking issues.
- Recommend revision instead of silently fixing unsupported references.

Output:
- `outputs/intermediate/citation_audit.json`
