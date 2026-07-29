from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.literature_review.cli import run_workbench
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench.server import _DEFAULT_STATIC_ROOT


def main() -> int:
    index_template = (_DEFAULT_STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    if "stream-state" not in index_template:
        raise RuntimeError("browser fixture imported stale Workbench static assets")
    port = int(os.environ.get("WORKBENCH_E2E_PORT", "8876"))
    with TemporaryDirectory(prefix="literature-review-e2e-") as temporary:
        root = Path(temporary)
        store = SQLiteWorkflowStore(root / "workflow.db")
        store.initialize()
        return run_workbench(
            store,
            root / "artifacts",
            host="127.0.0.1",
            port=port,
            open_browser=False,
            default_corpus_path=PROJECT_ROOT / "data" / "papers.json",
        )


if __name__ == "__main__":
    raise SystemExit(main())
