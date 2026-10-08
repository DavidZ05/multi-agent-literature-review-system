# Quick start

The application is local-first. Workflow state stays in SQLite and run
artifacts stay on disk unless you explicitly configure external literature or
model providers.

## Requirements

- macOS or Linux
- Python 3.11 or 3.12
- Git
- Node.js 20+ only when running browser tests

## Install

```bash
git clone https://github.com/DavidZ05/multi-agent-literature-review-system.git
cd multi-agent-literature-review-system
python3 -m pip install -e .
literature-review doctor
```

`doctor` creates local runtime storage and validates the packaged corpus and
configuration. It does not contact a model or literature provider.

## Open the Workbench

```bash
literature-review-workbench
```

The browser opens at `http://127.0.0.1:8765/`. The server rejects non-loopback
hosts and is not intended for public deployment.

## Run from the CLI

Create a persistent run from the bundled corpus:

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json
```

Inspect and continue it with the returned `run_id`:

```bash
literature-review status RUN_ID
literature-review events RUN_ID
literature-review resume RUN_ID
```

## Add automatic discovery

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

Discovery pauses at the corpus approval gate. Review pending candidates in the
Workbench or use the equivalent `approve`, `reject`, and `defer` CLI commands.

!!! note "Topic scope"
    Discovery and storage accept arbitrary topics. The bundled deterministic
    writing profile is specifically designed for memory-augmented LLM agents;
    topic-general synthesis remains a roadmap item.

## Next steps

- [Configure deterministic or API-backed agents](configuration.md)
- [Understand the stage and approval model](workflow.md)
- [Review reliability and audit controls](reliability.md)
