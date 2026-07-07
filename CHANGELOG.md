# Changelog

All notable changes to this project are documented here.

## 0.3.0 - 2026-07-07

### Added

- Installable Python package metadata and the `literature-review` console command.
- Packaged default seed corpus so the command works after editable installation.
- Trusted HTTPS certificate handling for arXiv and Semantic Scholar provider calls.
- Public project files for licensing, contribution workflow, and security guidance.
- Platform guard for persistent workflow commands on unsupported systems.
- Strict deterministic/API runtime configuration with key redaction.
- OpenAI-compatible chat client with sanitized retryable/permanent error handling.
- Model-backed Writer, Expert Review, Polish, and Evaluation/Reflection agent paths.
- Persistent workflow recovery for retryable API failures.
- Workbench runtime display for backend, model, executor, and safe error category.
- Public user README and archived course-project submission materials.

### Changed

- Persistent CLI help now uses the stable `literature-review` program name.
- Default one-shot output is written under the current working directory.
- The default documentation now explains installation, deterministic runs,
  discovery approval, optional API profiles, and troubleshooting before
  course-project context.
- Course-facing materials moved under `docs/course-project/`.

### Fixed

- API-backed generation now preserves the same artifact contracts and
  deterministic citation gates as local runs.
- Configuration errors fail before creating persistent run records.
- Workbench status refreshes show stable public error categories without
  leaking provider details or API keys.

### Notes

- macOS and Linux are the supported platforms for persistent workflows.
- Windows support is planned for a future release because the current run locks use POSIX advisory locking.
- arXiv and Semantic Scholar live provider tests remain opt-in to keep the
  default test suite offline-friendly.
