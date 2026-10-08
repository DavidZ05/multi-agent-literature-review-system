# Configuration

The deterministic backend is the default and requires no model credentials.

```env
AGENT_BACKEND=deterministic
AGENT_API_MODE=single
```

## OpenAI-compatible API

Create a local environment file:

```bash
cp .env.example .env
```

Set the backend and provider endpoint in `.env`, then load it into the current
shell:

```bash
set -a
source .env
set +a
literature-review doctor
```

Single-provider mode shares one endpoint and model configuration across eligible
generative agents. Multi-provider mode permits per-agent overrides while
preserving the same artifacts and protected verification roles.

!!! danger "Keep credentials local"
    `.env` is ignored by Git. Never put real credentials in Markdown, source
    files, screenshots, Issues, or audit bundles.

## Literature providers

arXiv requires no API key and is conservatively throttled. Semantic Scholar can
run without a key at a lower quota; set `SEMANTIC_SCHOLAR_API_KEY` locally when
you have one. Provider responses are cached and partial failures remain visible
in discovery events.

For the complete variable reference, see
[`docs/configuration.md`](https://github.com/DavidZ05/multi-agent-literature-review-system/blob/main/docs/configuration.md).
