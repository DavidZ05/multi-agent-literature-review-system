# Multi-Agent Literature Review System

[![CI](https://github.com/DavidZ05/multi-agent-literature-review-system/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidZ05/multi-agent-literature-review-system/actions/workflows/ci.yml)

A local-first workflow for running literature reviews with multiple agents. It can discover candidate papers, pause for human approval, draft a survey, run expert review, revise, polish, and verify citations before producing final artifacts.

The default mode is deterministic and works offline from the checked-in corpus. API-backed writing and review agents are optional and OpenAI-compatible, but the citation gates stay deterministic.

## Quick Start

Supported platforms: macOS or Linux with Python 3.11 or 3.12.

```bash
git clone https://github.com/DavidZ05/multi-agent-literature-review-system.git
cd multi-agent-literature-review-system
python3 -m pip install -e .
literature-review --help
literature-review doctor
```

`doctor` creates the local database and artifact directory when needed, then
checks the packaged seed corpus and deterministic/API configuration. It does
not call a remote model or literature provider.

Run the deterministic one-shot workflow:

```bash
literature-review
```

Expected output:

```json
{
  "status": "accepted",
  "survey": ".../outputs/survey.md",
  "review_report": ".../outputs/review_report.json",
  "final_verification": ".../outputs/final_verification.json",
  "evaluation_report": ".../outputs/evaluation_report.json"
}
```

Run the full test suite:

```bash
python3 -m unittest discover -s tests -v
```

## Workbench

Start the local browser workbench:

```bash
literature-review-workbench
```

`literature-review ui` remains available and is equivalent. The dedicated
command accepts `--db`, `--artifacts`, `--host`, `--port`, and `--no-browser`
directly.

The workbench serves a loopback-only site at `http://127.0.0.1:8765/`. It reads and writes the same local SQLite database and artifact directory as the CLI:

- `.review-workflow/workflow.db`
- `.review-workflow/artifacts/`

The UI can create runs, inspect status/events, approve or reject discovered candidates, close discovery, resume, cancel, and delete terminal runs. Every mutation shows the equivalent CLI command. The interface follows the browser language on first use, includes a Chinese/English toggle, and remembers the last manual language choice.

The selected run is stored in the URL and restored on reload. If no saved run
exists, the newest stored run is selected. Active queued/running Jobs are
recovered from the Workbench backend after a page refresh, so polling and the
Job status banner continue without switching away from the run being viewed.
Job history is stored in the same SQLite database. If the backend process stops
before a queued or running Job finishes, the next launch marks that Job
`interrupted` and shows a one-time Workbench notice. The research run and its
checkpoints remain available; use `Resume` after inspecting the run state.

Runtime paths go before the subcommand, while workbench options go after it:

```bash
literature-review \
  --db /path/to/workflow.db \
  --artifacts /path/to/artifacts \
  ui --port 8766 --no-browser
```

## Persistent CLI

Use persistent runs when you want resumable state:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json
```

The command returns a `run_id`.

```bash
literature-review status RUN_ID
literature-review events RUN_ID
literature-review list
literature-review resume RUN_ID
literature-review cancel RUN_ID
literature-review delete RUN_ID
```

Pressing `Ctrl+C` during an executable stage marks the run `paused`; `resume` continues from the last valid checkpoint. A checkpoint is reused only when the input fingerprint and recorded SHA-256 artifact hashes still match. Deletion is permanent and is allowed only for `cancelled`, `completed`, or `failed` runs.

The legacy command still works:

```bash
python3 -m src.memory_review_pipeline
```

## Deterministic and API Modes

Deterministic mode is the default:

```env
AGENT_BACKEND=deterministic
AGENT_API_MODE=single
```

This mode requires no model provider, no API key, and no network access for drafting. It is the safest starting point for local testing.

To use model-backed Writer, Expert Review, Polish, and Reflection agents, create a local `.env`:

```bash
cp .env.example .env
set -a
source .env
set +a
```

Single API profile:

```env
AGENT_BACKEND=api
AGENT_API_MODE=single
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=replace-with-model-name
AGENT_TEMPERATURE=0.2
AGENT_TIMEOUT_SECONDS=60
```

Multi-agent profile:

```env
AGENT_BACKEND=api
AGENT_API_MODE=multi
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=default-model

WRITER_AGENT_MODEL=writer-model
WRITER_AGENT_TEMPERATURE=0.4
POLISH_AGENT_MODEL=polish-model
POLISH_AGENT_TEMPERATURE=0.2
```

If `AGENT_BACKEND=api` is selected, incomplete API settings fail fast with a configuration error. The system does not silently fall back to deterministic generation. Runtime artifacts and workbench responses redact keys; keep `.env` local and never commit it.

Remote API base URLs must use HTTPS. Loopback endpoints such as
`http://127.0.0.1:11434/v1` remain available for local OpenAI-compatible
servers. Temperatures must be between `0.0` and `2.0`, and timeouts between
`1` and `600` seconds.

Supported per-agent prefixes include `WRITER_AGENT_`, `DOMAIN_EXPERT_AGENT_`, `STRUCTURE_MENTOR_AGENT_`, `REVIEW_SYNTHESIZER_AGENT_`, `POLISH_AGENT_`, and `EVALUATION_REFLECTION_AGENT_`. The deterministic Search, Citation Auditor, and Final Verification gates remain part of the safety design.

## Automatic Literature Discovery

Add `--discover` to search arXiv and Semantic Scholar before drafting:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

The workflow normalizes, deduplicates, and scores candidates, then waits at `awaiting_corpus_approval`. Candidate papers are not citable until a human approves them.

If discovery runs but produces zero approval candidates, the workflow now pauses instead of silently drafting from the seed corpus. The Workbench shows a discovery summary with provider query counts, result counts, provider failures such as Semantic Scholar rate limits, seed-corpus alignment hints, and suggested next actions. Use `close-discovery` only when continuing with the existing seed corpus is intentional.

```bash
literature-review candidates RUN_ID
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

literature-review close-discovery RUN_ID
literature-review resume RUN_ID
```

arXiv does not need a key. Semantic Scholar works with limited anonymous quota; set `SEMANTIC_SCHOLAR_API_KEY` in `.env` if you have one:

```env
SEMANTIC_SCHOLAR_API_KEY=
```

Provider responses are cached in SQLite for 24 hours. arXiv calls are spaced by at least three seconds, and Semantic Scholar calls use conservative throttling. If every provider fails, the run enters `retry_wait` and can be resumed later. If some providers succeed and others fail, the run remains inspectable: the Workbench reports partial failures and lets the user decide whether to retry discovery, adjust the topic, configure `SEMANTIC_SCHOLAR_API_KEY`, or continue with approved/seed material.

## Project Structure

```text
multi-agent-literature-review-system/
├── README.md
├── pyproject.toml
├── .env.example
├── data/
│   └── papers.json
├── docs/
│   ├── course-project/
│   │   ├── FINAL_SUBMISSION.md
│   │   ├── design_document.md
│   │   └── seed_corpus_review.md
│   └── implementation_plan.md
├── outputs/
├── prompts/
├── src/
│   ├── memory_review_pipeline.py
│   └── literature_review/
│       ├── api/
│       ├── discovery/
│       ├── job_state.py
│       ├── providers/
│       ├── storage/
│       │   └── jobs.py
│       ├── workbench/
│       └── workflow/
└── tests/
```

- `src/literature_review/`: canonical package implementation.
- `src/memory_review_pipeline.py`: backward-compatible module entrypoint.
- `data/papers.json`: verified seed corpus used by deterministic runs.
- `prompts/`: packaged model-agent prompt contracts.
- `outputs/`: default one-shot artifacts.
- `.review-workflow/`: ignored local persistent state created by CLI/workbench.

The canonical implementation is already split by responsibility. The legacy
`src/memory_review_pipeline.py` file contains no pipeline implementation; it is
only a compatibility wrapper for older module commands and imports.

## Anti-Hallucination Design

The Writer can only cite keys present in the approved corpus. The Citation Auditor rejects unknown citation keys and checks lightweight claim-source alignment. The Review Synthesizer feeds blocking findings back into Writer. Polish is followed by Final Verification, which rejects both added and removed citations. A persistent run reaches `completed` only when the orchestrator quality gate returns `accepted`; exhausted revision loops leave the run failed with diagnostic artifacts under `quality_gate/`. This keeps provenance inspectable even when model-backed agents are enabled.

## Troubleshooting

- `configuration_error`: check `.env`. API mode requires `AGENT_API_BASE_URL`, `AGENT_API_KEY`, and `AGENT_MODEL`.
- `retry_wait`: a provider or model request failed in a retryable way. Run `literature-review resume RUN_ID` later.
- No candidates in discovery: lower the topic specificity, increase `--max-results`, or try one provider at a time.
- Semantic Scholar quota: anonymous access is limited. Add `SEMANTIC_SCHOLAR_API_KEY` if you need steadier quota.
- SSL errors: HTTP clients use `certifi` by default. If your environment overrides certificates, check `SSL_CERT_FILE` and local proxy settings.
- Workbench will not open: run `literature-review ui --no-browser`, then open the printed loopback URL manually.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m pip wheel . --no-deps --wheel-dir dist
```

GitHub Actions runs these checks on macOS and Linux with Python 3.11 and 3.12,
then installs the built wheel and smoke-tests both console commands.

Live provider checks are opt-in:

```bash
RUN_LIVE_PROVIDER_TESTS=1 python3 -m unittest tests.test_live_providers -v
```

## Course Project Archive

The original course-facing materials are preserved under `docs/course-project/`:

- `docs/course-project/FINAL_SUBMISSION.md`
- `docs/course-project/design_document.md`
- `docs/course-project/seed_corpus_review.md`

They are useful for understanding the original assignment framing, but the root README now focuses on reusable local workflow usage.
