from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.models import WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workflow import (
    DraftingHandler,
    PersistentWorkflowEngine,
    PlanningHandler,
    StageExecutionError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m src.memory_review_pipeline")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".review-workflow/workflow.db"),
        help="SQLite workflow database path",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path(".review-workflow/artifacts"),
        help="persistent artifact root",
    )
    commands = parser.add_subparsers(dest="command")

    start = commands.add_parser("start", help="start a persistent review run")
    start.add_argument("--topic", required=True)
    start.add_argument("--corpus", required=True, type=Path)

    resume = commands.add_parser("resume", help="resume a stored run")
    resume.add_argument("run_id")

    status = commands.add_parser("status", help="show one stored run")
    status.add_argument("run_id")

    commands.add_parser("list", help="list stored runs")

    events = commands.add_parser("events", help="show a run event log")
    events.add_argument("run_id")

    cancel = commands.add_parser("cancel", help="cancel a stored run")
    cancel.add_argument("run_id")
    return parser


def _engine(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
) -> PersistentWorkflowEngine:
    runtime_config = AgentRuntimeConfig.from_env()
    return PersistentWorkflowEngine(
        store,
        LocalArtifactStore(artifact_root),
        {
            WorkflowStage.PLANNING: PlanningHandler(),
            WorkflowStage.DRAFTING: DraftingHandler(runtime_config),
        },
        runtime_config=runtime_config.public_dict(),
    )


def _print_json(value: Any, *, stream: Any | None = None) -> None:
    print(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True),
        file=sys.stdout if stream is None else stream,
    )


def _legacy_main() -> int:
    root = Path(__file__).resolve().parents[2]
    result = Orchestrator(
        corpus_path=root / "data" / "papers.json",
        output_dir=root / "outputs",
    ).run()
    _print_json(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return _legacy_main()

    args = _parser().parse_args(arguments)
    if args.command is None:
        return _legacy_main()

    store = SQLiteWorkflowStore(args.db)
    store.initialize()
    try:
        if args.command == "status":
            _print_json(store.get_run(args.run_id).to_dict())
            return 0
        if args.command == "list":
            _print_json([run.to_dict() for run in store.list_runs()])
            return 0
        if args.command == "events":
            _print_json([event.to_dict() for event in store.list_events(args.run_id)])
            return 0

        engine = _engine(store, args.artifacts)
        if args.command == "start":
            run = engine.start(args.topic, args.corpus)
        elif args.command == "resume":
            run = engine.resume(args.run_id)
        elif args.command == "cancel":
            run = engine.cancel(args.run_id)
        else:
            raise AssertionError(f"unhandled command: {args.command}")
        _print_json(run.to_dict())
        return 0
    except RunNotFoundError as exc:
        _print_json(
            {"error": "run_not_found", "run_id": str(exc)},
            stream=sys.stderr,
        )
        return 2
    except StageExecutionError as exc:
        _print_json(
            {"error": "stage_execution_failed", "message": str(exc)},
            stream=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        interrupted_run_id = getattr(args, "run_id", None)
        if interrupted_run_id is None:
            runs = store.list_runs()
            interrupted_run_id = runs[0].run_id if runs else None
        payload: dict[str, Any] = {"error": "interrupted", "status": "paused"}
        if interrupted_run_id is not None:
            payload["run_id"] = interrupted_run_id
        _print_json(payload, stream=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
