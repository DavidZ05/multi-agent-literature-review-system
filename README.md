# Multi-Agent Literature Review System

This project implements a multi-agent literature review pipeline for the final assignment. It uses deterministic Python agents and a verified paper corpus to generate a survey while preventing hallucinated citations. The agent runtime also has a configurable API profile interface, but no API is required: without API settings, every agent runs through the local deterministic implementation.

## Final Assignment Deliverables

| Requirement | File or Folder |
|---|---|
| System code / configuration | `src/memory_review_pipeline.py`, `.env.example`, `prompts/`, `data/papers.json` |
| Agent role prompts | `prompts/search_agent.md`, `prompts/writer_agent.md`, `prompts/reviewer_agent.md`, `prompts/polish_agent.md`, `prompts/orchestrator.md`, plus expert-review prompts |
| Generated survey report | `outputs/survey.md` |
| Design document | `docs/design_document.md` |
| Seed corpus review | `docs/seed_corpus_review.md` |
| Architecture and process explanation | `docs/design_document.md` |
| Citation and expert verification result | `outputs/review_report.json`, `outputs/final_verification.json` |
| Revision-loop record | `outputs/revision_log.json` |
| Evaluation and reflection | `outputs/evaluation_report.json`, `outputs/reflection_log.md` |
| Tests | `tests/test_pipeline.py` |
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
│   └── memory_review_pipeline.py
└── tests/
    └── test_pipeline.py
```

- `src/`: runnable multi-agent orchestration code.
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

## API Configuration

API use is optional. The current submission includes a configuration interface for future API-backed agents, while the runnable project still defaults to deterministic local logic. The current code records resolved API settings but does not require external requests to complete the assignment workflow.

Create a local env file if you want to experiment with API configuration:

```bash
cp .env.example .env
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

## Anti-Hallucination Design

The Writer Agent can only cite keys found in `data/papers.json`. The Citation Auditor parses the draft, rejects unknown citation keys, and performs lightweight claim-source alignment checks. The Review Synthesizer passes blocking feedback back to Writer. After Polish, the Final Verification Reviewer checks that no new citation was introduced. This makes citation provenance inspectable and reduces fabricated or mismatched references in the final survey.
