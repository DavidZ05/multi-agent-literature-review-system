# Security model

The Workbench is a single-user local application. GitHub Pages hosts only this
static documentation and never receives workflow state, API keys, paper text,
or local artifacts.

## Deployment boundary

- Workbench accepts only `127.0.0.1` or `localhost`.
- Mutation requests require a per-process token and loopback origin checks.
- The application has no user accounts or multi-user authorization.
- Do not expose it through public port forwarding or a shared reverse proxy.

## Data boundary

SQLite state, source PDFs, extracted passages, prompts, drafts, and audit exports
inherit local filesystem permissions. They are not encrypted by the project.
Remote providers receive only the queries or prompts needed for enabled features.

## Content and plugin risks

PDF parsers process complex files and plugins execute trusted Python code without
sandboxing. Import PDFs from trusted sources and install only reviewed plugins.

## Reporting

Use a private GitHub security advisory when available. Include the affected
command, operating system, Python version, a minimal reproduction, and whether
private data or credentials may be exposed.

Read the maintained
[`SECURITY.md`](https://github.com/DavidZ05/multi-agent-literature-review-system/blob/main/SECURITY.md)
before sharing a Workbench instance or audit export.
