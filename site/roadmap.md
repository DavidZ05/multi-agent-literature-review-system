# Roadmap

The maintained product is at v0.8.1. The next work is ordered by research
quality and workflow reliability rather than feature count.

## Next priorities

1. **Versioned ReviewProfile contract** for topic scope, inclusion criteria,
   required sections, review rubric, and deterministic writing strategy.
2. **Independent agent checkpoints** so an interrupted drafting stage can resume
   within the stage instead of restarting the complete attempt.
3. **Model-backed semantic claim verifier** behind the existing citation-scoped,
   fail-closed verification contract.
4. **OCR provenance** for scanned or low-quality PDFs.
5. **Side-by-side evidence review** with PDF page and passage navigation.
6. **Platform-neutral activity locking** with Windows coverage.

## Compatibility commitments

- Deterministic mode remains available without model credentials.
- Corpus approval, citation, checkpoint, and final-verification gates remain
  protected.
- SQLite migrations and artifact contracts are versioned public behavior.
- Legacy `python3 -m src.memory_review_pipeline` commands remain supported until
  a documented major-version removal.

Detailed implementation status lives in
[`docs/implementation_plan.md`](https://github.com/DavidZ05/multi-agent-literature-review-system/blob/main/docs/implementation_plan.md).
