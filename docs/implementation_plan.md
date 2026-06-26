# Implementation Plan

Goal: build an inspectable multi-agent literature review system that generates a survey on memory-augmented LLM agents while preserving citation integrity and reproducible agent handoffs.

1. Create a verified paper corpus in `data/papers.json`.
2. Define role prompts for Search, Writer, Citation Auditor, Domain Expert, Structure Mentor, Review Synthesizer, Polish, Final Verification, Evaluation / Reflection, and Orchestrator agents.
3. Write tests for corpus validation, survey generation, citation-audit failure, feedback-loop behavior, final verification, deterministic fallback, single API profiles, and multi-agent API overrides.
4. Implement a deterministic Python orchestrator using only standard-library modules.
5. Add an optional API runtime configuration interface while keeping deterministic local execution as the default.
6. Generate `outputs/survey.md`, `outputs/review_report.json`, `outputs/final_verification.json`, `outputs/evaluation_report.json`, and `outputs/reflection_log.md`.
7. Write a design document explaining architecture, handoffs, feedback loop, anti-hallucination controls, human intervention, pitfalls, and agent-level reflection.
8. Run tests and inspect generated outputs.
