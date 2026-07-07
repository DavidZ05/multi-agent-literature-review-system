# Workflow Design

This project is a local-first literature review workflow. The command line and
Workbench UI use the same SQLite store, artifact store, approval service, and
persistent workflow engine.

## Discovery Gate

Automatic discovery is intentionally not fully autonomous. arXiv and Semantic
Scholar results are normalized, deduplicated, screened, and stored as candidate
papers. Candidate papers cannot be cited until a human approves them.

The workflow pauses at `awaiting_corpus_approval` in two cases:

1. discovery produced candidate papers that require approve, reject, or defer
   decisions;
2. discovery ran but produced zero approval candidates.

The second case is important. A zero-candidate run may mean the topic is too
broad, the query wording is not scholarly enough, the seed corpus does not match
the topic, a provider is rate limited, or the provider simply returned no useful
records. The system therefore waits for human review instead of silently
drafting a survey from unrelated seed papers.

## Workbench Diagnostics

`WorkbenchService.get_run_detail()` exposes a `discovery_summary` object. The UI
uses it to show:

- whether discovery ran;
- provider query counts, result counts, and failure counts;
- sanitized provider error categories such as `rate_limited` or
  `network_unavailable`;
- candidate and pending counts;
- a lightweight seed-corpus alignment hint;
- recommended next actions.

For zero-candidate discovery runs, the Workbench changes the continuation action
from "Close discovery" to "Continue with seed corpus". This makes the human
decision explicit: continuing means the user accepts drafting from the current
verified seed corpus.

## Failure Policy

- All providers fail: the run enters `retry_wait`; resume retries from the last
  valid checkpoint.
- Some providers fail but at least one provider succeeds: discovery remains
  inspectable, and partial failures are shown in the Workbench.
- Discovery succeeds with zero candidates: the run waits for human review before
  drafting.
- Approved candidates exist: the approval gate builds an augmented corpus and
  drafting uses that corpus.
- No approved candidates and the user closes discovery: drafting uses the seed
  corpus only.

This policy favors transparent research control over hidden automation. The
system can still complete quickly, but only after the user has seen why no new
literature was added.
