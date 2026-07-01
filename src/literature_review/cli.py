from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from src.literature_review.discovery import ApprovalService
from src.literature_review.models import CandidateStatus, WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.runtime import build_engine, load_resume_settings
from src.literature_review.storage import (
    LocalArtifactStore,
    CandidateNotFoundError,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workflow import StageExecutionError


class _ExtendTupleAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Sequence[str],
        option_string: str | None = None,
    ) -> None:
        current = getattr(namespace, self.dest, self.default)
        if isinstance(current, tuple):
            current = []
        setattr(namespace, self.dest, [*current, *values])


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
    start.add_argument("--discover", action="store_true")
    start.add_argument(
        "--providers",
        nargs="+",
        action=_ExtendTupleAction,
        choices=("arxiv", "semantic_scholar"),
        default=("arxiv", "semantic_scholar"),
    )
    start.add_argument("--max-results", type=int, default=10)

    resume = commands.add_parser("resume", help="resume a stored run")
    resume.add_argument("run_id")

    status = commands.add_parser("status", help="show one stored run")
    status.add_argument("run_id")

    commands.add_parser("list", help="list stored runs")

    events = commands.add_parser("events", help="show a run event log")
    events.add_argument("run_id")

    cancel = commands.add_parser("cancel", help="cancel a stored run")
    cancel.add_argument("run_id")

    candidates = commands.add_parser("candidates", help="list discovered papers")
    candidates.add_argument("run_id")
    candidates.add_argument(
        "--status",
        choices=tuple(status.value for status in CandidateStatus),
    )

    approve = commands.add_parser("approve", help="approve one candidate")
    approve.add_argument("run_id")
    approve.add_argument("candidate_id")
    approve.add_argument("--reason", required=True)
    approve.add_argument("--category", required=True)
    approve.add_argument("--contribution", required=True)
    approve.add_argument("--tags", action="extend", nargs="+", required=True)

    for name in ("reject", "defer"):
        decision = commands.add_parser(name, help=f"{name} one candidate")
        decision.add_argument("run_id")
        decision.add_argument("candidate_id")
        decision.add_argument("--reason", required=True)

    close = commands.add_parser(
        "close-discovery", help="confirm all candidate decisions are complete"
    )
    close.add_argument("run_id")
    return parser


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
        if args.command == "candidates":
            status = None if args.status is None else CandidateStatus(args.status)
            _print_json(
                [
                    candidate.to_dict()
                    for candidate in store.list_candidates(args.run_id, status=status)
                ]
            )
            return 0
        approval = ApprovalService(store)
        if args.command == "approve":
            decision = approval.approve(
                args.run_id,
                args.candidate_id,
                reason=args.reason,
                category=args.category,
                contribution=args.contribution,
                tags=tuple(args.tags),
            )
            _print_json(decision.to_dict())
            return 0
        if args.command in {"reject", "defer"}:
            method = approval.reject if args.command == "reject" else approval.defer
            decision = method(
                args.run_id,
                args.candidate_id,
                reason=args.reason,
            )
            _print_json(decision.to_dict())
            return 0
        if args.command == "close-discovery":
            pending = store.list_candidates(args.run_id, status=CandidateStatus.PENDING)
            if pending:
                _print_json(
                    {
                        "error": "approval_required",
                        "pending_candidate_count": len(pending),
                    },
                    stream=sys.stderr,
                )
                return 3
            _print_json({"run_id": args.run_id, "status": "ready_to_resume"})
            return 0

        artifact_store = LocalArtifactStore(args.artifacts)
        if args.command == "resume":
            stored_run = store.get_run(args.run_id)
            if stored_run.current_stage == WorkflowStage.AWAITING_CORPUS_APPROVAL:
                pending = store.list_candidates(
                    args.run_id, status=CandidateStatus.PENDING
                )
                if pending:
                    _print_json(
                        {
                            "error": "approval_required",
                            "run_id": args.run_id,
                            "pending_candidate_count": len(pending),
                        },
                        stream=sys.stderr,
                    )
                    return 3
            enabled, providers, max_results = load_resume_settings(
                artifact_store, args.run_id
            )
            engine = build_engine(
                store,
                args.artifacts,
                discovery_enabled=enabled,
                providers=providers,
                max_results=max_results,
            )
        elif args.command == "start":
            engine = build_engine(
                store,
                args.artifacts,
                discovery_enabled=args.discover,
                providers=tuple(args.providers),
                max_results=args.max_results,
            )
        else:
            engine = build_engine(store, args.artifacts)

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
    except (RunNotFoundError, CandidateNotFoundError) as exc:
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
