from __future__ import annotations

import json
from pathlib import Path

from src.literature_review.orchestrator import Orchestrator


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    result = Orchestrator(
        corpus_path=root / "data" / "papers.json",
        output_dir=root / "outputs",
    ).run()
    print(json.dumps(result, indent=2))


__all__ = ["main"]
