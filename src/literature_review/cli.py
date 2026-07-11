from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence
import webbrowser

from src.literature_review.activity import (
    ActivityCoordinator,
    RunBusy,
    RunDeletionBusy,
    require_supported_platform,
)
from src.literature_review.config import AgentConfigurationError
from src.literature_review.discovery import ApprovalService
from src.literature_review.models import CandidateStatus, WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.runtime import build_engine, load_resume_settings
from src.literature_review.storage import (
    CandidateDecisionNotAllowedError,
    LocalArtifactStore,
    CandidateNotFoundError,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workflow import StageExecutionError
from src.literature_review.workbench.deletion import ArtifactDeletionManager
from src.literature_review.workbench.jobs import WorkflowJobManager
from src.literature_review.workbench.server import create_workbench_server
from src.literature_review.workbench.service import (
    RunDeletionConflictError,
    RunNotDeletableError,
    WorkbenchService,
)


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


def _port_number(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="literature-review")
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

    delete = commands.add_parser("delete", help="delete a terminal stored run")
    delete.add_argument("run_id")

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

    ui = commands.add_parser("ui", help="open the local review workbench")
    ui.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default="127.0.0.1",
    )
    ui.add_argument("--port", type=_port_number, default=8765)
    ui.add_argument(
        "--no-browser",
        action="store_true",
        help="serve the workbench without opening a browser",
    )
    return parser


def _print_json(value: Any, *, stream: Any | None = None) -> None:
    print(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True),
        file=sys.stdout if stream is None else stream,
    )


def _legacy_main() -> int:
    try:
        result = Orchestrator(
            corpus_path=_default_corpus_path(),
            output_dir=Path.cwd() / "outputs",
        ).run()
    except AgentConfigurationError as exc:
        _print_configuration_error(exc)
        return 2
    _print_json(result)
    return 0


def _default_corpus_path() -> Path:
    return Path(__file__).with_name("resources") / "papers.json"


def _print_configuration_error(exc: AgentConfigurationError) -> None:
    _print_json(
        {"error": "configuration_error", "message": str(exc)},
        stream=sys.stderr,
    )


def run_workbench(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
    *,
    host: str,
    port: int,
    open_browser: bool,
    default_corpus_path: Path,
) -> int:
    artifact_root = Path(artifact_root).expanduser().resolve()
    activity = ActivityCoordinator.for_artifact_root(artifact_root)
    manager = WorkflowJobManager(store, artifact_root)
    server = None
    try:
        deletion_manager = ArtifactDeletionManager(artifact_root)
        service = WorkbenchService(
            store,
            cancel=lambda run_id: build_engine(
                store,
                artifact_root,
            ).cancel(run_id),
            deletion_manager=deletion_manager,
        )
        try:
            def run_exists(run_id: str) -> bool:
                try:
                    store.get_run(run_id)
                except RunNotFoundError:
                    return False
                return True

            reconciliation = deletion_manager.reconcile_pending(
                run_exists,
                activity=activity,
            )
            if reconciliation.unresolved:
                print(
                    "Warning: "
                    f"{reconciliation.unresolved} artifact quarantines "
                    "need manual recovery.",
                    file=sys.stderr,
                )
        except Exception:
            print(
                "Warning: artifact reconciliation failed; continuing.",
                file=sys.stderr,
            )
        server = create_workbench_server(
            service,
            manager,
            host=host,
            port=port,
            default_corpus_path=default_corpus_path,
        )
        url = f"http://{host}:{server.server_address[1]}/"
        print(f"Literature Review Workbench: {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        manager.shutdown(wait=True)
        if server is not None:
            server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return _legacy_main()

    args = _parser().parse_args(arguments)
    if args.command is None:
        return _legacy_main()

    require_supported_platform()

    store = SQLiteWorkflowStore(args.db)
    store.initialize()
    try:
        if args.command == "ui":
            return run_workbench(
                store,
                args.artifacts,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
                default_corpus_path=_default_corpus_path(),
            )
        if args.command == "status":
            _print_json(store.get_run(args.run_id).to_dict())
            return 0
        if args.command == "list":
            _print_json([run.to_dict() for run in store.list_runs()])
            return 0
        if args.command == "events":
            _print_json([event.to_dict() for event in store.list_events(args.run_id)])
            return 0
        if args.command == "delete":
            service = WorkbenchService(store, artifact_root=args.artifacts)
            _print_json(service.delete_run(args.run_id))
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

        if args.command == "resume":
            reservation = ActivityCoordinator.for_artifact_root(
                args.artifacts
            ).reserve_resume(args.run_id)
            try:
                with reservation.activate():
                    stored_run = store.get_run(args.run_id)
                    if (
                        stored_run.current_stage
                        == WorkflowStage.AWAITING_CORPUS_APPROVAL
                    ):
                        pending = store.list_candidates(
                            args.run_id,
                            status=CandidateStatus.PENDING,
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
                    artifact_store = LocalArtifactStore(args.artifacts)
                    enabled, providers, max_results = load_resume_settings(
                        artifact_store,
                        args.run_id,
                    )
                    engine = build_engine(
                        store,
                        args.artifacts,
                        discovery_enabled=enabled,
                        providers=providers,
                        max_results=max_results,
                    )
                    run = engine.resume(args.run_id)
            finally:
                reservation.release()
            _print_json(run.to_dict())
            return 0

        if args.command == "start":
            engine = build_engine(
                store,
                args.artifacts,
                discovery_enabled=args.discover,
                providers=tuple(args.providers),
                max_results=args.max_results,
            )
            run = engine.start(args.topic, args.corpus)
        elif args.command == "cancel":
            engine = build_engine(store, args.artifacts)
            run = engine.cancel(args.run_id)
        else:
            raise AssertionError(f"unhandled command: {args.command}")
        _print_json(run.to_dict())
        return 0
    except RunNotDeletableError as exc:
        _print_json(
            {
                "error": "run_not_deletable",
                "run_id": exc.run_id,
                "status": exc.status.value,
            },
            stream=sys.stderr,
        )
        return 3
    except CandidateDecisionNotAllowedError as exc:
        _print_json(
            {
                "error": "approval_not_allowed",
                "run_id": exc.run_id,
                "candidate_id": exc.candidate_id,
            },
            stream=sys.stderr,
        )
        return 3
    except RunDeletionConflictError as exc:
        _print_json(
            {
                "error": "run_deletion_conflict",
                "run_id": exc.run_id,
                "expected_status": exc.expected_status.value,
                "actual_status": exc.actual_status.value,
            },
            stream=sys.stderr,
        )
        return 3
    except (RunBusy, RunDeletionBusy) as exc:
        payload = {
            "error": (
                "run_busy" if isinstance(exc, RunBusy) else "run_deletion_busy"
            )
        }
        if exc.run_id is not None:
            payload["run_id"] = exc.run_id
        _print_json(payload, stream=sys.stderr)
        return 3
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
    except AgentConfigurationError as exc:
        _print_configuration_error(exc)
        return 2
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


__all__ = ["main", "run_workbench"]
