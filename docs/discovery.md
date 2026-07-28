# Literature Discovery and Approval

Automatic discovery is domain-neutral, but it is intentionally not fully
autonomous. Papers returned by arXiv or Semantic Scholar are normalized,
deduplicated, screened, and held for human approval before Writer can cite them.

## Start Discovery

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

The default planner creates topic, survey, evaluation, and reliability query
variants. Repeat `--query` to provide up to eight exact scholarly queries:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --query "memory augmented language agents survey" \
  --query "long term memory evaluation for LLM agents"
```

The run waits at `awaiting_corpus_approval`, including when discovery succeeds
but produces zero approval candidates. This prevents silent drafting from an
unrelated seed corpus.

## Review Candidates

```bash
literature-review candidates RUN_ID --status pending

literature-review approve RUN_ID CANDIDATE_ID \
  --reason "Core evidence" \
  --category "memory mechanism" \
  --contribution "Introduces a reflective memory mechanism." \
  --tags memory reflection

literature-review reject RUN_ID CANDIDATE_ID \
  --reason "Outside the review scope"

literature-review defer RUN_ID CANDIDATE_ID \
  --reason "Full text should be checked first"
```

After every candidate has a decision:

```bash
literature-review close-discovery RUN_ID
literature-review resume RUN_ID
```

Closing a zero-candidate discovery run explicitly accepts drafting from the
current seed corpus.

## Retry Discovery

Retry inside the same run after rate limiting, narrow queries, or poor results:

```bash
literature-review retry-discovery RUN_ID \
  --providers arxiv \
  --max-results 20 \
  --query "memory augmented language agents" \
  --query "LLM agent memory benchmark"

literature-review discovery-attempts RUN_ID
```

Each retry is durable. Existing candidates and append-only human decisions are
preserved; new papers are deduplicated against the accumulated pool. Attempt
records store provider selection, queries, limits, failures, and the
retrieved/normalized/deduplicated/screened/new-candidate funnel.

Every corpus decision stores the exact candidate snapshot and a canonical
SHA-256 fingerprint. Screening scores, recommendations, and provider provenance
may be refreshed without invalidating a decision. A change to bibliographic,
identifier, source, abstract, or PDF metadata returns the candidate to `pending`
so the earlier human decision cannot authorize different material later.

Provider responses are cached in SQLite for 24 hours. arXiv calls are spaced by
at least three seconds, and Semantic Scholar calls use conservative throttling.
If every provider fails, the run enters `retry_wait`. Partial failures remain
inspectable and do not discard successful results.

## Topic Scope

Discovery queries can target any scholarly topic. The bundled deterministic
Writer, Citation Auditor, Domain Expert, and structure template are currently
optimized for the included memory-augmented LLM agent survey. For a different
domain, discovery can still build and approve a corpus, but final synthesis
requires a future topic-general ReviewProfile. Replacing Writer alone does not
replace the protected review rubric.
