# Contributing

Thanks for improving this literature review workflow. The project is designed to stay useful as a local-first research assistant, so contributions should keep reproducibility, citation integrity, and clear failure modes in mind.

## Development Setup

Use Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the test suite before opening a pull request:

```bash
python3 -m unittest discover -s tests -v
```

Provider smoke tests may contact external services and should only be run when you explicitly want live network checks:

```bash
RUN_LIVE_PROVIDER_TESTS=1 python3 -m unittest tests.test_live_providers -v
```

## Pull Request Guidelines

- Keep changes scoped to one behavior or workflow improvement.
- Add or update tests for behavior changes.
- Preserve deterministic citation and final verification gates.
- Do not commit local databases, generated run artifacts, API keys, or personal paper collections.
- Keep macOS and Linux behavior working unless the change is explicitly platform-specific.

## Commit Style

Use short imperative commit messages, for example:

```text
Add provider timeout diagnostics
```
