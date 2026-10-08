# Development Status and Roadmap

This document describes the maintained product as of v0.8.1. The original
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
- Append-only Agent execution journals with per-attempt manifests, versioned
  Writer drafts, expert reports, and SQLite stage events that survive failure or
  interruption.
- Versioned claims, fingerprint-bound human evidence decisions, historical PDF
  evidence retention, and deterministic audit ZIP export.
- Fingerprint-bound corpus decisions, run-scoped evidence chunk identities,
  fail-closed post-Polish semantic anchors, and staged transactional PDF import.
- Exclusive per-database Workbench ownership that prevents one backend from
  interrupting another backend's live durable Jobs.
- Replayable Job requests with bounded automatic restart recovery and a durable
  SQLite event feed consumed through Server-Sent Events.
- macOS/Linux packaging and CI across Python 3.11 and 3.12, plus real Chromium
  Workbench tests for completion, refresh recovery, selection, and localization.
- Public GitHub Pages documentation with strict builds, an English core guide,
  a Chinese quick start, and an explicit static-site security boundary.

## Next Priorities

1. Introduce a versioned `ReviewProfile` contract for topic, inclusion criteria,
   required sections, domain rubric, and deterministic writing strategy. Keep
   the current memory-agent profile as the default and add a topic-general
   profile only after its citation and quality behavior has regression tests.
2. Promote the Agent execution journal into independently resumable Agent
   checkpoints. In v0.8.0 the journal survives interruption, but an interrupted
   Drafting attempt restarts the complete Drafting stage from its last workflow
   checkpoint.
3. Continue the compatibility-preserving modularization with
   `storage/sqlite.py`, followed by `workbench/server.py` and `cli.py`. Keep thin
   facades at existing import paths and do not change public commands, artifacts,
   database behavior, or plugin contracts.
4. Add a model-backed semantic claim verifier behind the existing verification
   result contract. It must remain citation-scoped and cannot bypass blocking
   statuses or human review.
5. Add optional OCR for scanned or low-quality PDFs, recording the OCR engine,
   version, and derived-text provenance in document artifacts.
6. Improve evidence review with side-by-side PDF page viewing and passage-level
   navigation in the Workbench.
7. Add Windows-compatible activity locking after preserving the current
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
