# Reliability and audit

The system treats a literature review as a controlled research process rather
than a single model response.

## Blocking gates

| Gate | What it prevents |
| --- | --- |
| Corpus approval | Unreviewed discovery results entering the citable corpus |
| Citation-key validation | References to unknown or renamed sources |
| Writer revision loop | Reviewer feedback being recorded without reaching Writer |
| Post-polish verification | Fluency edits changing citations or factual direction |
| Evidence review | Unsupported claims silently passing when full-text checks are enabled |

## Durable artifacts

Each run stores versioned drafts, reviewer reports, revision instructions,
evaluation results, events, manifests, and final exports. Agent execution
journals preserve attempts even when an execution is interrupted.

## Full-text evidence verification

PDF verification is opt-in and citation-scoped. Imported PDFs are validated,
parsed, chunked with provenance, and matched against claims associated with that
citation. Human decisions are bound to the claim and corpus fingerprints so
materially changed evidence cannot silently inherit an old approval.

!!! warning "What this does not guarantee"
    Structural and semantic gates reduce common failure modes; they do not prove
    scientific truth or replace expert reading of the cited papers.

## Export

The audit ZIP can include run state, decisions, model attempts, review reports,
evidence results, and final Markdown. Inspect exports before sharing: depending
on options, they may contain local paths, extracted text, prompts, or source
PDFs.
