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
| 0.8.1   | Yes       |
| <= 0.8.0 | No       |

## Intended Deployment

The Workbench is a single-user local application, not a multi-user web service.
It only accepts `127.0.0.1` or `localhost` as its listening host. Do not expose it
through a reverse proxy, SSH tunnel shared with untrusted users, public port
forwarding, or a container configuration that publishes it beyond the local
machine.

One Workbench backend may own a SQLite database at a time. An exclusive POSIX
lock is acquired before durable Job recovery, preventing a second local backend
from marking the first instance's live Jobs as interrupted. The lock file may
remain on disk after shutdown; ownership is the operating-system lock, not file
existence.

Workbench mutations require a per-process token injected into the served page.
Every request must also carry a loopback `Host` header matching the active
server, and mutations check browser origins and a per-process token. The server
applies a restrictive Content Security Policy, denies framing, disables response
caching, and limits JSON request-body size. These controls reduce DNS-rebinding
and local browser attacks; they do not provide user accounts, authorization
between users, or protection for a public deployment.

The GitHub Pages website is a separate, read-only static documentation surface.
It does not proxy the Workbench, read local SQLite state, accept API keys, or
process research artifacts.

The read-only Server-Sent Events endpoint carries sanitized Job and workflow
change metadata. Its cursor is a local monotonically increasing event ID; it
does not stream prompts, API keys, paper text, or generated survey content.
EventSource reconnects replay missed change notifications from SQLite, while
all mutations continue to require the token and origin checks above.

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

The discovery providers use HTTPS and a trusted CA bundle. Credentialed provider
requests, including Semantic Scholar requests with `x-api-key`, reject redirects
so the credential cannot be forwarded to a redirect target. PDF acquisition
accepts HTTPS only, validates DNS results and redirect targets before following
them, rejects localhost or non-public addresses, applies a size limit, and
requires a PDF signature. Provider errors avoid exposing credentials in
user-facing messages.

Model API calls reject redirects instead of forwarding authenticated requests
to a different location. Configure `AGENT_API_BASE_URL` and per-agent overrides
with the provider's final HTTPS endpoint. Loopback HTTP endpoints remain allowed
only for explicitly configured local OpenAI-compatible servers.

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
