# Changelog

All notable changes to this project are documented here.

## 0.3.0 - 2026-07-07

### Added

- Installable Python package metadata and the `literature-review` console command.
- Packaged default seed corpus so the command works after editable installation.
- Trusted HTTPS certificate handling for arXiv and Semantic Scholar provider calls.
- Public project files for licensing, contribution workflow, and security guidance.
- Platform guard for persistent workflow commands on unsupported systems.

### Changed

- Persistent CLI help now uses the stable `literature-review` program name.
- Default one-shot output is written under the current working directory.

### Notes

- macOS and Linux are the supported platforms for persistent workflows.
- Windows support is planned for a future release because the current run locks use POSIX advisory locking.
