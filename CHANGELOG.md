# Changelog

All notable changes to this project are documented here.

## Unreleased

## 0.8.0 - 2026-07-28

### Added

- Persisted replay-safe Job requests and recovery counters in SQLite schema
  version 7 for Workbench `start`, `resume`, and discovery-retry operations.
- Automatic same-Job recovery after backend restart, bounded to three attempts
  and backed by existing workflow checkpoints and artifact hash validation.
- A bounded durable Workbench event feed and same-origin Server-Sent Events
  endpoint with event IDs, reconnect replay, heartbeats, and polling fallback.
- Playwright Chromium tests for local run completion, streamed UI updates,
  selected-run restoration, and bilingual preference persistence.
- A dedicated GitHub Actions browser job with failure traces and screenshots.

### Changed

- Old Jobs without a persisted replay request, malformed requests, and Jobs at
  the recovery limit remain fail-closed as `interrupted` for human inspection.
- The Workbench shows live-update connection state and reduces background
  polling while its event stream is healthy.

## 0.7.3 - 2026-07-28

### Fixed

- Scoped deterministic evidence-chunk identifiers to the run, document, and
  citation so the same PDF can be indexed safely in multiple workflows.
- Added a fail-closed post-Polish semantic gate for negation, numeric values,
  directional language, comparison, modality, and named factual anchors.
- Kept trailing citations on their own atomic clause instead of broadcasting
  them to unrelated clauses earlier in the sentence.
- Bound corpus decisions to a SHA-256 fingerprint and exact candidate snapshot;
  materially changed discovery metadata now returns to pending approval.
- Added an exclusive per-database Workbench process lock so a second backend
  cannot interrupt Jobs owned by a live instance.
- Staged and parsed imported PDFs before atomically replacing the current
  document and evidence chunks, with file rollback on database failure.

- Increment `ResearchRun.revision_count` atomically when human evidence review
  returns a run to Drafting, and distinguish that workflow-level count from
  per-Drafting Writer iterations and revisions in generated audit artifacts.
- Isolate Markdown table rows during atomic-claim extraction so citations cannot
  leak across rows.
- Pause orphaned active Runs during Workbench restart recovery, preserving their
  stage and making Resume available after the associated Job is interrupted.
- Reject redirects for credentialed literature-provider requests, including
  Semantic Scholar API-key requests.
- Normalize nonblocking Synthesizer advisory output to accepted and require
  actionable `must_fix` feedback for model-requested revision loops.
- Report the actual deterministic backend for protected Search, Citation Auditor,
  and Final Verification agents even when model APIs are enabled elsewhere.
- Defer full-text Evaluation until claim verification and any human evidence
  review have completed, and include the final evidence outcome in scoring.

## 0.7.2 - 2026-07-18

### Fixed

- Blocked high-risk factual claims that contain quantitative or explicit
  research-result language but no approved citation, including claims introduced
  by Writer or Polish when full-text verification is disabled.
- Made Final Verification compare citation occurrence order, citation context,
  headings, and reference entries in addition to citation-key membership.
- Normalized Expert Panel and full-text evidence feedback for the deterministic
  Writer, and record a stalled revision instead of repeating an unchanged draft.
- Rejected model API redirects so an Authorization header cannot be forwarded to
  another origin.
- Required every Workbench request to use a loopback Host matching the local
  server, closing the read-side DNS-rebinding gap.

### Changed

- Persist each Drafting execution under `agent_runs/attempt_NNN/`, including
  versioned Writer drafts, per-iteration expert reports, a sanitized attempt
  manifest, and SQLite `agent_stage_completed` events.
- Split the Workbench application layer into focused run, discovery, evidence,
  export, diagnostics, command, and presentation modules. The existing
  `WorkbenchService` remains a compatibility facade with unchanged public
  methods and response contracts.
- Hardened model-agent prompts against instructions embedded in payload text,
  required complete grounded Writer output, and made Polish preserve citation
  keys and their claim association exactly.

### Documentation

- Expanded the local deployment threat model, secret handling, PDF/plugin risk,
  and audit-export guidance in `SECURITY.md`.
- Replaced the completed early implementation checklist with a v0.7.2 status
  and compatibility-preserving roadmap.
- Added a documentation map that separates maintained product documentation
  from the course-project archive.
- Reduced the root README to the primary user path and moved API configuration,
  discovery operations, and full-text evidence details into maintained guides.
- Documented the boundary between domain-neutral workflow infrastructure and
  the bundled memory-agent deterministic review profile.

## 0.7.1 - 2026-07-16

### Fixed

- Unified citation-key parsing and validation across Corpus, Writer, Citation
  Auditor, Final Verification, and claim extraction. Citation keys containing
  underscores or hyphens can no longer bypass the unknown-citation gate.
- Bound human evidence decisions to the exact blocking verification
  fingerprints they reviewed. PDF refreshes and verifier changes now preserve
  old decisions as audit history while requiring a new decision for new
  evidence.
- Refreshed document and evidence manifests after local PDF import, and included
  evidence chunks, discovery attempts, candidates, and corpus decisions directly
  in audit manifests. Replaced parsed PDFs and their chunks are archived so
  earlier claim versions remain resolvable.
- Made repeated claim-verification execution idempotent for an unchanged survey
  instead of creating a new draft version after an interrupted stage.
- Restricted evidence decisions and local PDF imports to a run waiting at the
  evidence gate, with the same per-run activity lock used by workflow execution.
- Validated PDF host DNS results and every redirect target before following the
  request, rejecting localhost and non-public addresses before content is read.

## 0.7.0 - 2026-07-15

### Added

- Opt-in `--full-text` stages for HTTPS PDF acquisition, local PDF import,
  page-aware parsing, deterministic evidence chunks, atomic claims, and
  citation-scoped claim verification.
- SQLite schema version 6 for documents, evidence chunks, versioned claims,
  verification results, and append-only human evidence decisions.
- A human evidence gate with `require_revision` for unsupported claims and
  narrowly scoped `accept_risk` decisions when full text is unavailable.
- Workbench claim-evidence inspection, source snippets with page numbers, local
  PDF import, evidence decisions, and audit export controls.
- Reproducible audit ZIP export with stable entry metadata and a SHA-256 file
  manifest.
- End-to-end regression coverage proving evidence feedback reaches the next
  Writer run and invalidates the previous drafting checkpoint.

### Changed

- Full-text runs now execute `acquiring_documents`, `indexing_evidence`, and
  post-polish `claim_verification` before completion.
- Writer revision control artifacts include human decision IDs and source draft
  versions, while prior claim versions remain available for audit.
- Local PDF import immediately reverifies the latest claim version and replaces
  stale verification results in one SQLite transaction.
- The artifact store now supports atomically written binary artifacts using the
  same path-containment and checksum rules as text and JSON.

### Safety Notes

- The deterministic verifier is a conservative passage-alignment gate, not a
  substitute for expert factual review. Retrieval never crosses citation keys.
- Risk acceptance cannot override missing citations, contradictions, partial
  support, or evidence not found; it is limited to unavailable full text.
- PDF acquisition accepts HTTPS sources with a PDF signature and does not
  bypass paywalls.

## 0.5.1 - 2026-07-14

### Added

- Persistent discovery-attempt history with per-attempt providers, exact query
  text, result funnel, failures, and artifact summaries.
- Same-run discovery retry from the CLI and Workbench, including single-provider
  retry and editable scholarly queries.
- `literature-review discovery-attempts RUN_ID` for inspecting retrieval history.
- Workbench discovery funnel and bilingual retry controls.

### Changed

- arXiv searches now use bounded keyword conjunctions instead of treating a
  long generated query as one exact phrase.
- Default query suggestions are domain-neutral topic, survey, evaluation, and
  reliability searches.
- Discovery retries merge new candidates without overwriting existing candidate
  decisions. Backend restarts mark active attempts as interrupted and return an
  interrupted retry to its previous review gate.
- arXiv query tokenization preserves Unicode terms, including Chinese topics.
- SQLite schema version 5 adds discovery attempts without altering existing runs,
  candidates, decisions, events, checkpoints, or Jobs.

## 0.5.0 - 2026-07-12

### Added

- Provider and Agent plugin registries with standard Python entry-point
  discovery.
- Dynamic Workbench provider controls generated from installed plugins.
- `literature-review plugins` for inspecting provider sources, Agent sources,
  installed versions, and protected roles.
- A public plugin-development guide with packaging and contract examples.

### Changed

- Runtime artifacts record selected providers, the active Agent manifest, and
  plugin distribution versions for checkpoint reproducibility.
- Search, citation review, and final verification are protected core roles;
  replaceable Agent plugins cannot override these safety gates.
- Built-in providers remain enabled by default, while third-party providers
  require explicit selection for each new run.

## 0.4.0 - 2026-07-11

### Added

- Durable Workbench Job records in SQLite, including sanitized results and
  errors.
- Automatic reconciliation that marks queued or running Jobs `interrupted`
  after a Workbench backend restart.
- A one-time bilingual Workbench notice for interrupted Jobs.
- `literature-review doctor` for first-run database, artifact, corpus, and
  agent-configuration checks.
- The `literature-review-workbench` command as a direct local UI launcher.
- CI wheel builds, installed-command smoke tests, and source compilation.

### Changed

- SQLite schema version 4 adds `workflow_jobs` without altering existing runs,
  candidates, decisions, events, or checkpoints.
- Job state and its SQLite repository are separate modules, so Workbench
  execution, persistence, and schema migration have explicit boundaries.
- Public setup instructions now start with the local diagnostic command and
  the dedicated Workbench launcher.

## 0.3.1 - 2026-07-10

### Fixed

- Final verification now rejects polish output that adds or removes citations.
- Persistent runs no longer report `completed` when the orchestrator exhausts
  its revision loop without an accepted draft; diagnostic artifacts are kept
  under `quality_gate/`.
- Candidate decisions are accepted only while a run is waiting at the corpus
  approval gate and the candidate is still pending.
- Workbench run selection keeps active Job polling in the current page while
  preserving real links for modified-click and new-tab navigation.
- Workbench page reloads recover queued and running Jobs from the backend
  without replacing the user's selected run.
- Initial Workbench loading selects an available run without overriding a
  previously selected run during refresh or background polling.
- Remote model API URLs require HTTPS, while loopback HTTP remains available
  for local model servers; temperature and timeout ranges are validated.

### Changed

- Workbench retains a bounded history of completed in-memory Jobs.
- Provider cache writes prune expired response rows.
- Public clone instructions now point to the canonical GitHub repository.

## 0.3.0 - 2026-07-07

### Added

- Installable Python package metadata and the `literature-review` console command.
- Packaged default seed corpus so the command works after editable installation.
- Trusted HTTPS certificate handling for arXiv and Semantic Scholar provider calls.
- Public project files for licensing, contribution workflow, and security guidance.
- Platform guard for persistent workflow commands on unsupported systems.
- Strict deterministic/API runtime configuration with key redaction.
- OpenAI-compatible chat client with sanitized retryable/permanent error handling.
- Model-backed Writer, Expert Review, Polish, and Evaluation/Reflection agent paths.
- Persistent workflow recovery for retryable API failures.
- Workbench runtime display for backend, model, executor, and safe error category.
- Public user README and archived course-project submission materials.

### Changed

- Persistent CLI help now uses the stable `literature-review` program name.
- Default one-shot output is written under the current working directory.
- The default documentation now explains installation, deterministic runs,
  discovery approval, optional API profiles, and troubleshooting before
  course-project context.
- Course-facing materials moved under `docs/course-project/`.

### Fixed

- API-backed generation now preserves the same artifact contracts and
  deterministic citation gates as local runs.
- Configuration errors fail before creating persistent run records.
- Workbench status refreshes show stable public error categories without
  leaking provider details or API keys.

### Notes

- macOS and Linux are the supported platforms for persistent workflows.
- Windows support is planned for a future release because the current run locks use POSIX advisory locking.
- arXiv and Semantic Scholar live provider tests remain opt-in to keep the
  default test suite offline-friendly.
