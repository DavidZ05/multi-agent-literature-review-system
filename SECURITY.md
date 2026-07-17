# Security

This project is local-first. It stores workflow state in SQLite and run artifacts on disk, and it can optionally call external literature providers. Treat local run artifacts as research data because they may contain paper metadata, prompts, notes, and generated review drafts.

## Supported Versions

Security fixes are accepted for the latest public version.

| Version | Supported |
| ------- | --------- |
| 0.7.x   | Yes       |
| < 0.7   | No        |

## Reporting a Vulnerability

Please open a private security advisory on GitHub if the repository enables advisories. If advisories are unavailable, contact the maintainer privately before publishing details.

Useful reports include:

- affected command or workflow;
- operating system and Python version;
- reproduction steps using a minimal corpus when possible;
- whether secrets, local paths, or private research data may be exposed.

## Secret Handling

- Never commit `.env` files or API keys.
- Prefer environment variables for provider and model credentials.
- Do not paste provider keys into issue logs, screenshots, generated reports, or workbench event payloads.
- When sharing a failing run, redact local paths and remove `.review-workflow` artifacts unless the contents are safe to disclose.

## Network Behavior

The discovery providers use HTTPS and a trusted CA bundle. PDF acquisition
validates DNS results and redirect targets before following them, and rejects
localhost or non-public addresses. Provider errors should avoid leaking full
query URLs or credentials in user-facing messages.
