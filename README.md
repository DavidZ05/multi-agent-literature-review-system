# Multi-Agent Literature Review System

[![CI](https://github.com/DavidZ05/multi-agent-literature-review-system/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidZ05/multi-agent-literature-review-system/actions/workflows/ci.yml)

A local-first, inspectable workflow for literature discovery, human corpus
approval, multi-agent drafting and review, citation verification, optional PDF
evidence checking, and reproducible audit export.

The bundled deterministic review profile targets **memory-augmented LLM
agents**. Discovery, persistence, approval, evidence, and audit infrastructure
are reusable across topics; arbitrary-domain final synthesis still requires a
future topic-general review profile. Agent plugins can customize generative
roles, but they do not replace the protected review rubric.

## Quick Start

Supported platforms: macOS or Linux with Python 3.11 or 3.12.

```bash
git clone https://github.com/DavidZ05/multi-agent-literature-review-system.git
cd multi-agent-literature-review-system
python3 -m pip install -e .
literature-review --help
literature-review doctor
```

`doctor` initializes local storage and checks the packaged corpus and runtime
configuration without contacting a model or literature provider.

Run the bundled deterministic review once:

```bash
literature-review
```

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

## Workbench

Start the local bilingual Workbench:

```bash
literature-review-workbench
```

`literature-review ui` is equivalent. The server only accepts `127.0.0.1` or
`localhost` and uses the same SQLite database and artifacts as the CLI:

```text
.review-workflow/workflow.db
.review-workflow/artifacts/
```

Only one Workbench backend may own a database at a time. A second launch exits
with a clear error instead of changing the live instance's durable Job state.

The UI creates and resumes runs, reviews candidates and claim evidence, imports
local PDFs, exports results, and manages terminal runs. Selection survives page
reloads; active Job state is recovered without switching away from the run being
viewed. Every mutation displays its equivalent CLI command.

Custom paths precede the subcommand:

```bash
literature-review \
  --db /path/to/workflow.db \
  --artifacts /path/to/artifacts \
  ui --port 8766 --no-browser
```

## Persistent CLI

Create a resumable run:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json
```

The command returns a `run_id` used by management commands:

```bash
literature-review status RUN_ID
literature-review events RUN_ID
literature-review list
literature-review resume RUN_ID
literature-review cancel RUN_ID
literature-review delete RUN_ID
```

`Ctrl+C` pauses an executable stage. Resume continues from the latest valid
checkpoint only when its input fingerprint and artifact hashes still match.
Deletion is permanent and is restricted to terminal runs.

The legacy entrypoint remains available:

```bash
python3 -m src.memory_review_pipeline
```

## Deterministic and API Modes

Deterministic mode is the default and requires no model API:

```env
AGENT_BACKEND=deterministic
AGENT_API_MODE=single
```

To use OpenAI-compatible model-backed agents:

```bash
cp .env.example .env
set -a
source .env
set +a
```

```env
AGENT_BACKEND=api
AGENT_API_MODE=single
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=replace-with-model-name
```

Multi-agent mode supports separate models, temperatures, keys, and timeouts for
Writer, Domain Expert, Structure Mentor, Review Synthesizer, Polish, and
Evaluation / Reflection. Search, Citation Auditor, and Final Verification remain
deterministic protected roles.

See [Runtime Configuration](docs/configuration.md) for single and per-agent
profiles, local model endpoints, validation rules, and secret handling.

## Automatic Literature Discovery

Search arXiv and Semantic Scholar before drafting:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

New papers are normalized, deduplicated, screened, and held at
`awaiting_corpus_approval`. They cannot be cited until a human approves them.
A decision records the exact candidate snapshot and fingerprint reviewed;
material metadata changes discovered later require a new decision.
A zero-candidate run also waits instead of silently drafting from a potentially
unrelated seed corpus.

```bash
literature-review candidates RUN_ID --status pending
literature-review close-discovery RUN_ID
literature-review resume RUN_ID
literature-review retry-discovery RUN_ID --providers arxiv --max-results 20
```

arXiv needs no key. Semantic Scholar supports limited anonymous use; configure
`SEMANTIC_SCHOLAR_API_KEY` for steadier quota. See
[Literature Discovery and Approval](docs/discovery.md) for approval, rejection,
deferral, exact queries, retries, and failure behavior.

## Full-Text Evidence Verification

Enable citation-scoped PDF verification:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --full-text
```

The workflow acquires or imports PDFs, extracts page-aware chunks, splits the
final survey into atomic claims, and retrieves evidence only from each claim's
own citation key. Unsupported results wait for human evidence review. Final
evaluation runs only after this evidence gate accepts or records allowed risk.
Local replacements are parsed from a staging path before the current PDF and
its SQLite evidence index are switched atomically.

```bash
literature-review documents RUN_ID
literature-review evidence RUN_ID
literature-review import-pdf RUN_ID CITATION_KEY /path/to/paper.pdf
literature-review export RUN_ID --output RUN_ID-audit.zip
```

See [Full-Text Evidence Verification](docs/evidence_verification.md) for decision
rules, fingerprint-bound approvals, PDF replacement history, and audit contents.

## Safety Model

- Only human-approved corpus records become Writer-visible.
- Writer citations must belong to the approved allowlist.
- Citation Auditor checks unknown keys, high-risk facts without citations,
  required structure, and lightweight metadata alignment.
- Reviewer feedback returns to Writer; deterministic and API Writers consume the
  same blocking claim fields, and an unchanged revision is marked stalled.
- Polish is prompted to make wording-only changes. Final Verification rejects
  citation count, order, context, heading, reference, high-risk factual, or
  protected semantic-anchor drift and retains the accepted pre-polish draft.
- Optional full-text verification blocks unresolved claim-evidence failures.
- Full-text Evaluation runs after claim verification and includes the final
  evidence decision; it is not emitted while human evidence review is pending.
- Each Drafting attempt keeps versioned drafts, panel reports, and Agent events
  under `agent_runs/attempt_NNN/` for interruption-safe auditing.

These controls make evidence use inspectable; they do not replace expert reading
or guarantee scientific correctness. See [Workflow Design](docs/workflow_design.md)
and [Security](SECURITY.md) for exact contracts and operating boundaries.

## Plugins

Inspect installed provider and agent plugins:

```bash
literature-review plugins
literature-review doctor
```

Plugins use standard Python entry points. Provider plugins extend discovery;
agent plugins may replace generative roles. Protected Search, Citation Auditor,
and Final Verification roles cannot be replaced. Plugins are trusted Python code
and are not sandboxed.

See [Plugin Development](docs/plugin_development.md) for contracts and packaging
examples.

## Documentation

- [Documentation Map](docs/README.md)
- [Runtime Configuration](docs/configuration.md)
- [Literature Discovery and Approval](docs/discovery.md)
- [Full-Text Evidence Verification](docs/evidence_verification.md)
- [Workflow Design](docs/workflow_design.md)
- [Plugin Development](docs/plugin_development.md)
- [Development Status and Roadmap](docs/implementation_plan.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

Runtime API-agent prompts live in `src/literature_review/prompts/`. The root
`prompts/` directory is the archived course-facing role specification and does
not affect runtime behavior.

## Project Structure

```text
data/                         verified seed corpus
docs/                         maintained guides and course archive
outputs/                      default one-shot artifacts
prompts/                      archived course role specifications
src/literature_review/        canonical package
  documents/                  PDF acquisition and parsing
  discovery/                  search, normalization, screening, approval
  plugins/                    provider and agent registries
  storage/                    artifacts and SQLite persistence
  verification/               claims, retrieval, evidence decisions
  workbench/                  local HTTP UI and application services
  workflow/                   persistent state machine and handlers
tests/                        regression and integration tests
```

`src/memory_review_pipeline.py` and `WorkbenchService` are compatibility facades;
the implementation is split into focused package modules.

## Troubleshooting

- `configuration_error`: validate `.env` with `literature-review doctor`.
- `retry_wait`: inspect events and resume after the provider becomes available.
- No candidates: adjust exact queries, increase `--max-results`, or retry one
  provider at a time.
- Workbench does not open: run `literature-review ui --no-browser` and open the
  printed loopback URL.
- `awaiting_evidence_review`: inspect evidence, import a PDF, or record a human
  decision before resuming.
- SSL errors: clients use `certifi`; check `SSL_CERT_FILE` and local proxy
  settings when certificate overrides are active.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m pip wheel . --no-deps --wheel-dir dist
```

GitHub Actions runs the suite and wheel smoke tests on macOS and Linux with
Python 3.11 and 3.12. Live provider checks are opt-in:

```bash
RUN_LIVE_PROVIDER_TESTS=1 python3 -m unittest tests.test_live_providers -v
```

## Course Project Archive

The original assignment-facing materials remain under `docs/course-project/`,
including `docs/course-project/FINAL_SUBMISSION.md`. They preserve the project
history and are not the current product manual.
