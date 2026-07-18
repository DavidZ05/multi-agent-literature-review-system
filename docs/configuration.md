# Runtime Configuration

The deterministic backend is the default and requires no model credentials:

```env
AGENT_BACKEND=deterministic
AGENT_API_MODE=single
```

It performs drafting with the bundled memory-agent survey template. Literature
discovery still uses the network when `--discover` is enabled.

## Load Local Environment Variables

Create a local file from the checked-in template:

```bash
cp .env.example .env
set -a
source .env
set +a
```

`set -a` makes variables loaded by `source` available to child processes;
`set +a` restores normal shell behavior. Never commit `.env`.

## Single API Profile

```env
AGENT_BACKEND=api
AGENT_API_MODE=single
AGENT_API_BASE_URL=https://api.example.com/v1
AGENT_API_KEY=replace-with-your-key
AGENT_MODEL=replace-with-model-name
AGENT_TEMPERATURE=0.2
AGENT_TIMEOUT_SECONDS=60
```

All replaceable model-backed agents use this profile. Incomplete API settings
fail fast; the system does not silently fall back to deterministic generation.

## Per-Agent Profiles

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

Supported prefixes are:

- `WRITER_AGENT_`
- `DOMAIN_EXPERT_AGENT_`
- `STRUCTURE_MENTOR_AGENT_`
- `REVIEW_SYNTHESIZER_AGENT_`
- `POLISH_AGENT_`
- `EVALUATION_REFLECTION_AGENT_`

Each prefix may override `API_BASE_URL`, `API_KEY`, `MODEL`, `TEMPERATURE`, and
`TIMEOUT_SECONDS`. Search, Citation Auditor, and Final Verification remain
protected deterministic roles.

Remote API base URLs must use HTTPS. Loopback endpoints such as
`http://127.0.0.1:11434/v1` are allowed for local OpenAI-compatible servers.
Temperatures must be between `0.0` and `2.0`; timeouts must be between `1` and
`600` seconds. Model API redirects are rejected so authenticated requests are
not forwarded to another location; configure the final endpoint directly.

## Literature Provider Credentials

arXiv requires no key. Semantic Scholar supports limited anonymous use; add a
key for steadier quota:

```env
SEMANTIC_SCHOLAR_API_KEY=
```

Run `literature-review doctor` after changing configuration. Public runtime
artifacts redact API keys, but a remote model provider receives the prompts and
source material assigned to its agents. Review [SECURITY.md](../SECURITY.md)
before using private corpora.
