# Security

This project is local-first. It stores workflow state in SQLite and run artifacts
on disk, and it can optionally call external literature providers and model
APIs. Treat local run artifacts as research data because they may contain paper
metadata, prompts, notes, generated review drafts, extracted PDF text, and human
review decisions.

## Supported Versions

Security fixes are accepted for the latest public version.

| Version | Supported |
| ------- | --------- |
| 0.7.1   | Yes       |
| <= 0.7.0 | No       |

## Intended Deployment

The Workbench is a single-user local application, not a multi-user web service.
It only accepts `127.0.0.1` or `localhost` as its listening host. Do not expose it
through a reverse proxy, SSH tunnel shared with untrusted users, public port
forwarding, or a container configuration that publishes it beyond the local
machine.

Workbench mutations require a per-process token injected into the served page.
The server also checks browser origins, applies a restrictive Content Security
Policy, denies framing, disables response caching, and limits JSON request-body
size. These controls reduce local browser attacks; they do not provide user
accounts, authorization between users, or protection for a public deployment.

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
- A configured remote model API receives the prompts and source material needed
  by its assigned agents. Review the provider's data policy before sending
  private corpora or unpublished research notes.

## Network Behavior

The discovery providers use HTTPS and a trusted CA bundle. PDF acquisition
accepts HTTPS only, validates DNS results and redirect targets before following
them, rejects localhost or non-public addresses, applies a size limit, and
requires a PDF signature. Provider errors avoid exposing credentials in
user-facing messages.

These checks are defense in depth, not a hardened network sandbox. Do not use
the downloader as a general-purpose fetch proxy or process attacker-controlled
URLs on a hostile network. Automatic discovery also sends the research topic
and generated queries to the selected literature providers.

## PDFs, Plugins, and Local Data

- PDF parsers process complex, potentially untrusted files in the Workbench
  process. Import only documents from sources you trust and keep dependencies
  updated. The project does not provide malware scanning or parser sandboxing.
- Plugins are trusted Python code and are not sandboxed. Installing a plugin
  gives it the same local access as the Workbench process.
- SQLite state, artifacts, source PDFs, and exports inherit local filesystem
  permissions and are not encrypted by this project. Protect the user account
  and storage volume appropriately.
- Audit ZIP files may contain source PDFs, extracted passages, prompts, local
  paths, and review history. Use `--no-pdfs` when source documents should not be
  redistributed, and inspect an export before sharing it.
