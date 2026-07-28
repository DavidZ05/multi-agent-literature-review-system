# Full-Text Evidence Verification

Full-text verification is opt-in because it downloads or imports PDFs and adds
a strict claim-evidence completion gate.

## Start a Full-Text Run

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --full-text
```

It can be combined with `--discover`. Approved candidates are merged into the
corpus before document acquisition.

```text
acquiring_documents -> indexing_evidence -> drafting
-> claim_verification -> evaluating -> completed
                     \-> awaiting_evidence_review -> drafting | evaluating
```

The downloader accepts HTTPS PDFs, validates public DNS and every redirect,
applies a size limit, and requires a PDF signature. arXiv abstract URLs are
converted to official PDF URLs. The project does not bypass access controls.

`pdfplumber` extracts page-aware text and stable evidence chunks. Claim
retrieval is hard-scoped to the claim's own citation key. A passage from another
paper cannot satisfy the result.

## Inspect and Repair Evidence

```bash
literature-review documents RUN_ID
literature-review claims RUN_ID
literature-review evidence RUN_ID
```

Import a legally obtained PDF when automatic acquisition is unavailable:

```bash
literature-review import-pdf RUN_ID CITATION_KEY /path/to/paper.pdf
```

The latest claims are reverified immediately. If a parsed PDF is replaced, its
prior file, metadata, and chunks are archived so earlier claim versions remain
resolvable in the audit trail.

Record a human decision and resume:

```bash
literature-review evidence-decide RUN_ID CLAIM_ID \
  --action require_revision \
  --reason "The cited passage does not support the broad claim"

literature-review resume RUN_ID
```

`accept_risk` is allowed only for `full_text_unavailable`. It cannot override a
missing citation, contradiction, partial support, or evidence-not-found result.
Every decision is bound to the exact verification fingerprints reviewed; a PDF
or verifier change leaves the old decision in history but makes it inactive.
Returning a run to Drafting increments its durable `revision_count` exactly once;
restarting or resuming the same checkpoint does not inflate the audit count.
Final evaluation is deferred until this gate accepts the evidence state. Runs
waiting for evidence decisions therefore have no stable final evaluation report;
after acceptance, the report records the claim-verification and human-review
outcome used for scoring.

## Audit Export

```bash
literature-review export RUN_ID --output RUN_ID-audit.zip
```

The deterministic ZIP includes run artifacts, events, discovery attempts,
candidate and corpus decisions, documents, chunks, claims, verification
results, human decisions, and file checksums. Source PDFs are included by
default; add `--no-pdfs` when they should not be redistributed.

The deterministic verifier is conservative. `supported` means a
citation-scoped passage contains the material terms of the claim; it is not a
guarantee of expert scientific correctness. Central conclusions still require
reading the cited pages. Scanned PDFs may be marked `low_quality`; OCR is not
included in v0.7.2.
