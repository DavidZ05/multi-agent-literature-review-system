# Plugins

The project exposes Python entry-point registries for literature providers and
generative agents.

```bash
literature-review plugins
literature-review doctor
```

## Provider plugins

Provider plugins extend discovery. They return normalized candidates through a
stable contract so the existing deduplication, screening, approval, and retry
logic still applies.

## Agent plugins

Agent plugins can replace eligible generative roles such as Writer, expert
reviewers, synthesizer, and Polisher. Protected Search, Citation Auditor, and
Final Verification roles are not replaceable.

## Trust boundary

Plugins execute as normal Python code inside the local process. They are not
sandboxed and receive the same filesystem and network access as the application.
Install only packages you trust.

See the complete
[plugin contract](https://github.com/DavidZ05/multi-agent-literature-review-system/blob/main/docs/plugin_development.md)
for entry-point names, data models, and examples.
