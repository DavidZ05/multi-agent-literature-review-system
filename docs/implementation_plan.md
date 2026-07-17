# Development Status and Roadmap

This document describes the maintained product as of v0.7.1. The original
course submission is archived under `docs/course-project/`.

## Implemented

- Deterministic and optional OpenAI-compatible multi-agent execution.
- A bundled deterministic review profile for memory-augmented LLM agents, with
  an explicit scope boundary distinct from domain-neutral discovery and storage.
- Persistent SQLite workflow state, checkpoints, resume, cancellation, recovery,
  retention, and reproducible run artifacts.
- arXiv and Semantic Scholar discovery with durable retries, deduplication,
  screening, and mandatory human corpus approval.
- A local bilingual Workbench backed by the same services and database as the
  CLI.
- A thin `WorkbenchService` compatibility facade delegating to focused run,
  discovery, evidence, export, diagnostics, and presentation modules.
- Plugin registries for literature providers and replaceable generative agents,
  with protected citation and final-verification roles.
- Citation-key validation, Writer feedback loops, post-polish verification, and
  opt-in citation-scoped PDF evidence verification.
- Versioned claims, fingerprint-bound human evidence decisions, historical PDF
  evidence retention, and deterministic audit ZIP export.
- macOS/Linux packaging and CI across Python 3.11 and 3.12.

## Next Priorities

1. Introduce a versioned `ReviewProfile` contract for topic, inclusion criteria,
   required sections, domain rubric, and deterministic writing strategy. Keep
   the current memory-agent profile as the default and add a topic-general
   profile only after its citation and quality behavior has regression tests.
2. Continue the compatibility-preserving modularization with
   `storage/sqlite.py`, followed by `workbench/server.py` and `cli.py`. Keep thin
   facades at existing import paths and do not change public commands, artifacts,
   database behavior, or plugin contracts.
3. Add a model-backed semantic claim verifier behind the existing verification
   result contract. It must remain citation-scoped and cannot bypass blocking
   statuses or human review.
4. Add optional OCR for scanned or low-quality PDFs, recording the OCR engine,
   version, and derived-text provenance in document artifacts.
5. Improve evidence review with side-by-side PDF page viewing and passage-level
   navigation in the Workbench.
6. Add Windows-compatible activity locking after preserving the current
   interruption and concurrency semantics in platform-neutral tests.

## Compatibility Rules

- Keep deterministic mode available without model credentials.
- Do not present discovery topic flexibility as topic-general synthesis until a
  compatible ReviewProfile controls every writing and review role.
- Preserve citation, corpus-approval, checkpoint, and final-verification gates.
- Treat SQLite migrations and artifact contracts as versioned public behavior.
- Keep legacy `python3 -m src.memory_review_pipeline` imports and commands working
  until a documented major-version removal.
- Add characterization tests before moving behavior between modules.
