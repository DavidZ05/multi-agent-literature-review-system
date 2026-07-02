# Multi-Agent Literature Review System

This project implements a durable multi-agent literature review workflow. It uses deterministic Python agents and a verified paper corpus to generate a survey while preventing hallucinated citations. Runs can be persisted, inspected, resumed, and cancelled locally. The agent runtime also has a configurable API profile interface, but no API is required: without API settings, every agent runs through the local deterministic implementation.

## Final Assignment Deliverables

| Requirement | File or Folder |
|---|---|
| System code / configuration | `src/memory_review_pipeline.py`, `src/literature_review/`, `.env.example`, `prompts/`, `data/papers.json` |
| Agent role prompts | `prompts/search_agent.md`, `prompts/writer_agent.md`, `prompts/reviewer_agent.md`, `prompts/polish_agent.md`, `prompts/orchestrator.md`, plus expert-review prompts |
| Generated survey report | `outputs/survey.md` |
| Design document | `docs/design_document.md` |
| Seed corpus review | `docs/seed_corpus_review.md` |
| Architecture and process explanation | `docs/design_document.md` |
| Citation and expert verification result | `outputs/review_report.json`, `outputs/final_verification.json` |
| Revision-loop record | `outputs/revision_log.json` |
| Evaluation and reflection | `outputs/evaluation_report.json`, `outputs/reflection_log.md` |
| Tests | `tests/test_pipeline.py`, `tests/test_module_boundaries.py` |
| Submission summary | `FINAL_SUBMISSION.md` |

## Project Structure

```text
multi-agent-literature-review-system/
├── README.md
├── FINAL_SUBMISSION.md
├── .env.example
├── data/
│   └── papers.json
├── docs/
│   ├── design_document.md
│   ├── implementation_plan.md
│   └── seed_corpus_review.md
├── outputs/
│   ├── survey.md
│   ├── review_report.json
│   ├── final_verification.json
│   ├── evaluation_report.json
│   ├── reflection_log.md
│   ├── revision_log.json
│   ├── runtime_config.json
│   └── intermediate/
├── prompts/
├── src/
│   ├── __init__.py
│   ├── memory_review_pipeline.py
│   └── literature_review/
│       ├── __init__.py
│       ├── base.py
│       ├── config.py
│       ├── corpus.py
│       ├── search.py
│       ├── writing.py
│       ├── review.py
│       ├── evaluation.py
│       ├── models.py
│       ├── orchestrator.py
│       ├── cli.py
│       ├── runtime.py
│       ├── discovery/
│       ├── providers/
│       ├── storage/
│       │   ├── artifacts.py
│       │   └── sqlite.py
│       ├── workbench/
│       │   ├── jobs.py
│       │   ├── server.py
│       │   ├── service.py
│       │   └── static/
│       └── workflow/
│           ├── checkpoints.py
│           ├── engine.py
│           ├── handlers.py
│           └── state.py
└── tests/
    ├── test_models.py
    ├── test_module_boundaries.py
    ├── test_persistent_cli.py
    ├── test_pipeline.py
    ├── test_storage.py
    └── test_workflow_engine.py
```

- `src/literature_review/`: canonical implementation modules organized by responsibility: corpus loading, runtime configuration, agent logic, orchestration, evaluation, and CLI entrypoints.
- `src/memory_review_pipeline.py`: backward-compatible command and import entrypoint that re-exports the package API for existing `python -m` and `from src.memory_review_pipeline import ...` usage.
- `src/literature_review/workbench/`: loopback-only browser interface, JSON API, and background-job adapter over the same persistent workflow used by the CLI.
- `data/`: verified source memory used by Search Agent.
- `prompts/`: role prompts for each agent.
- `outputs/`: generated survey, audits, verification reports, and run logs.
- `docs/`: design report, seed-corpus review, and implementation notes.
- `tests/`: workflow, citation-safety, feedback-loop, and configuration tests.

## Agent Workflow

```text
Search
  -> Writer
  -> Expert Review Panel
     -> Citation Auditor
     -> Domain Expert
     -> Structure Mentor
  -> Review Synthesizer
  -> Writer Revision Loop
  -> Polish
  -> Final Verification Reviewer
  -> Evaluation / Reflection Agent
```

The hard safety gate is citation integrity: unknown citation keys, unsupported claim-citation pairs, and missing required sections trigger revision. The expert reviewers add academic-quality feedback and scoring. The Final Verification Reviewer runs after polishing so that a style-editing step cannot silently introduce a new citation or claim.

## Run

Use the legacy-compatible module entrypoint below to invoke the modular workflow:

```bash
python3 -m src.memory_review_pipeline
```

By default this uses deterministic local agents. This is the recommended mode for grading and local testing because it does not need network access or API keys.

Expected result:

```json
{
  "status": "accepted",
  "survey": ".../outputs/survey.md",
  "review_report": ".../outputs/review_report.json",
  "final_verification": ".../outputs/final_verification.json",
  "evaluation_report": ".../outputs/evaluation_report.json"
}
```

## Persistent Workflow

Use the persistent command when a run must survive process exit or may need to
be inspected and resumed:

```bash
python3 -m src.memory_review_pipeline start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json
```

The command returns a `run_id`. State is stored in
`.review-workflow/workflow.db`, and run-scoped artifacts are stored under
`.review-workflow/artifacts/runs/<run_id>/`.

```bash
python3 -m src.memory_review_pipeline status RUN_ID
python3 -m src.memory_review_pipeline events RUN_ID
python3 -m src.memory_review_pipeline list
python3 -m src.memory_review_pipeline resume RUN_ID
python3 -m src.memory_review_pipeline cancel RUN_ID
```

Pressing `Ctrl+C` during an executable stage marks the run `paused` and exits
with status 130. `resume` continues from the last valid checkpoint. A checkpoint
is reused only when its input fingerprint matches and every recorded output
artifact still has the expected SHA-256 hash.

Custom runtime locations must appear before the subcommand:

```bash
python3 -m src.memory_review_pipeline \
  --db /path/to/workflow.db \
  --artifacts /path/to/artifacts \
  status RUN_ID
```

### Local Workbench

Start the browser workbench from the repository root:

```bash
python3 -m src.memory_review_pipeline ui
```

The command serves a loopback-only site at `http://127.0.0.1:8765/` and opens
the default browser. It reads and writes the same
`.review-workflow/workflow.db` and `.review-workflow/artifacts` used by the
persistent CLI. Existing runs therefore appear immediately, and decisions made
in the browser can be inspected or replayed through the Bash commands below.

The workbench supports run creation, status and event inspection, candidate
filtering, approve/reject/defer decisions, discovery closure, resume, and
cancellation. Every mutation displays its equivalent CLI command. The
interface follows the browser language on first use, offers a Chinese/English
toggle, and remembers the last manual choice.

Runtime locations still precede the subcommand; workbench-only options follow
it:

```bash
python3 -m src.memory_review_pipeline \
  --db /path/to/workflow.db \
  --artifacts /path/to/artifacts \
  ui --port 8766 --no-browser
```

`--port` accepts `0` through `65535` and defaults to `8765`; port `0` asks the
operating system to choose a free port. `--no-browser` starts the server without
opening a tab. The host is restricted to `127.0.0.1` or `localhost`, and
mutation requests require a per-process token injected into the served page.
Press `Ctrl+C` in the terminal to stop the workbench.

In the new-run dialog, **Maximum results per query** is the browser equivalent
of `--max-results`. It defaults to `10` and accepts values from `1` to `50`.
When discovery is enabled, at least one of arXiv or Semantic Scholar must be
selected.

### Automatic Literature Discovery

Add `--discover` to query arXiv and Semantic Scholar before drafting:

```bash
python3 -m src.memory_review_pipeline start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

The workflow searches, normalizes, deduplicates, and scores candidates, then
stops with `status=waiting` at `awaiting_corpus_approval`. Discovered papers
cannot be cited at this point and have no citation key.

```bash
python3 -m src.memory_review_pipeline candidates RUN_ID
python3 -m src.memory_review_pipeline candidates RUN_ID --status pending

python3 -m src.memory_review_pipeline approve RUN_ID CANDIDATE_ID \
  --reason "Core evidence" \
  --category "memory mechanism" \
  --contribution "Introduces a reflective memory mechanism." \
  --tags memory reflection

python3 -m src.memory_review_pipeline reject RUN_ID CANDIDATE_ID \
  --reason "Outside the review scope"

python3 -m src.memory_review_pipeline defer RUN_ID CANDIDATE_ID \
  --reason "Full text should be checked first"

python3 -m src.memory_review_pipeline close-discovery RUN_ID
python3 -m src.memory_review_pipeline resume RUN_ID
```

`resume` is refused while any candidate remains pending. Approved candidates
receive deterministic citation keys, are merged with the seed corpus, and pass
the existing corpus validator before Writer can see them. Writer generates
evidence paragraphs from every approved category, so newly approved papers
enter the body discussion as well as the references.

Provider responses are cached in SQLite for 24 hours. arXiv calls are spaced by
at least three seconds; Semantic Scholar calls use conservative throttling.
Partial provider failure is recorded and successful results continue. If every
provider fails, the run enters `retry_wait` and can be resumed later.

## API Configuration

There are two separate API concerns:

- Literature discovery uses public arXiv and Semantic Scholar endpoints.
- Agent generation still defaults to deterministic local logic; its API profile
  remains an extension interface.

arXiv needs no account or key. Semantic Scholar also permits limited anonymous
requests; an optional key can improve quota:

```env
SEMANTIC_SCHOLAR_API_KEY=
```

The key is sent only in the `x-api-key` header. It is never written to URLs,
events, SQLite records, artifacts, or command output.

Create a local env file if you want to experiment with API configuration:

```bash
cp .env.example .env
set -a
source .env
set +a
```

Keep `.env` local and do not submit it, because it may contain API keys. Submit `.env.example` only. The generated `outputs/runtime_config.json` sanitizes keys as `<configured>` when a key is present.

### Mode 1: No API

Use this for normal local testing:

```env
AGENT_BACKEND=deterministic
AGENT_API_MODE=single
```

### Mode 2: Single API Profile

All agents share one default API profile:

```env
AGENT_BACKEND=api
AGENT_API_MODE=single
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=replace-with-model-name
AGENT_TEMPERATURE=0.2
AGENT_TIMEOUT_SECONDS=60
```

### Mode 3: Multi-Agent API Profile

Agents inherit the default profile, but individual agents can override it:

```env
AGENT_BACKEND=api
AGENT_API_MODE=multi
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=default-model

WRITER_AGENT_MODEL=writer-model
WRITER_AGENT_TEMPERATURE=0.4

REVIEWER_AGENT_MODEL=reviewer-model
REVIEWER_AGENT_TEMPERATURE=0.0

POLISH_AGENT_MODEL=polish-model
POLISH_AGENT_TEMPERATURE=0.2
```

Supported agent prefixes are `SEARCH_AGENT_`, `WRITER_AGENT_`, `REVIEWER_AGENT_`, `DOMAIN_EXPERT_AGENT_`, `STRUCTURE_MENTOR_AGENT_`, `REVIEW_SYNTHESIZER_AGENT_`, `POLISH_AGENT_`, `FINAL_VERIFICATION_AGENT_`, and `EVALUATION_REFLECTION_AGENT_`.

Supported override suffixes are `API_BASE_URL`, `API_KEY`, `MODEL`, `TEMPERATURE`, and `TIMEOUT_SECONDS`. If an API profile is incomplete, the artifact records deterministic fallback and the local implementation remains usable.

For this final project, API configuration demonstrates extensibility. The required reproducible run is still the deterministic local run.

## Test

```bash
python3 -m unittest discover -s tests -v
```

This suite uses recorded provider fixtures and does not need network access.
Optional live checks request at most two records per provider:

```bash
RUN_LIVE_PROVIDER_TESTS=1 python3 -m unittest tests.test_live_providers -v
```

## Anti-Hallucination Design

The Writer Agent can only cite keys found in `data/papers.json`. The Citation Auditor parses the draft, rejects unknown citation keys, and performs lightweight claim-source alignment checks. The Review Synthesizer passes blocking feedback back to Writer. After Polish, the Final Verification Reviewer checks that no new citation was introduced. This makes citation provenance inspectable and reduces fabricated or mismatched references in the final survey.
