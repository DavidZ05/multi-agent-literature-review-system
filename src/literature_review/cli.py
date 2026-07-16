from __future__ import annotations

import argparse
import json
import os
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
from src.literature_review.config import AgentConfigurationError, AgentRuntimeConfig
from src.literature_review.corpus import load_papers
from src.literature_review.discovery import ApprovalService
from src.literature_review.documents.service import DocumentImportService
from src.literature_review.exporting import export_audit_bundle
from src.literature_review.models import CandidateStatus, WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.plugins import (
    AgentPluginError,
    ProviderPluginError,
    build_agent_factory,
    build_provider_registry,
)
from src.literature_review.runtime import (
    build_engine,
    load_resume_full_text,
    load_resume_query_texts,
    load_resume_settings,
    retry_discovery,
)
from src.literature_review.storage import (
    CandidateDecisionNotAllowedError,
    LocalArtifactStore,
    CandidateNotFoundError,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.version import VERSION
from src.literature_review.verification import (
    EvidenceReviewDecision,
    VerificationStatus,
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


def _query_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 300:
        raise argparse.ArgumentTypeError(
            "query must contain 1 to 300 non-whitespace characters"
        )
    return normalized


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="literature-review")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
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
        "--full-text",
        action="store_true",
        help="download or import PDFs and run claim-level evidence verification",
    )
    start.add_argument(
        "--providers",
        nargs="+",
        action=_ExtendTupleAction,
        default=("arxiv", "semantic_scholar"),
        metavar="PROVIDER",
        help="registered provider id; repeat or provide multiple values",
    )
    start.add_argument("--max-results", type=int, default=10)
    start.add_argument(
        "--query",
        action="append",
        type=_query_text,
        default=[],
        help="exact scholarly query; repeat up to eight times",
    )

    retry_discovery_parser = commands.add_parser(
        "retry-discovery",
        help="run another literature discovery attempt for an existing run",
    )
    retry_discovery_parser.add_argument("run_id")
    retry_discovery_parser.add_argument(
        "--providers",
        nargs="+",
        action=_ExtendTupleAction,
        default=("arxiv", "semantic_scholar"),
        metavar="PROVIDER",
    )
    retry_discovery_parser.add_argument("--max-results", type=int, default=10)
    retry_discovery_parser.add_argument(
        "--query",
        action="append",
        type=_query_text,
        default=[],
    )

    resume = commands.add_parser("resume", help="resume a stored run")
    resume.add_argument("run_id")

    status = commands.add_parser("status", help="show one stored run")
    status.add_argument("run_id")

    commands.add_parser("list", help="list stored runs")

    events = commands.add_parser("events", help="show a run event log")
    events.add_argument("run_id")

    attempts = commands.add_parser(
        "discovery-attempts",
        help="show saved discovery attempt history",
    )
    attempts.add_argument("run_id")

    documents = commands.add_parser("documents", help="list full-text document state")
    documents.add_argument("run_id")

    claims = commands.add_parser("claims", help="list extracted atomic claims")
    claims.add_argument("run_id")

    evidence = commands.add_parser(
        "evidence",
        help="show claim-level verification results",
    )
    evidence.add_argument("run_id")

    evidence_decide = commands.add_parser(
        "evidence-decide",
        help="record a claim evidence review decision",
    )
    evidence_decide.add_argument("run_id")
    evidence_decide.add_argument("claim_id")
    evidence_decide.add_argument(
        "--action",
        choices=("accept_risk", "require_revision"),
        required=True,
    )
    evidence_decide.add_argument("--reason", required=True)

    import_pdf = commands.add_parser(
        "import-pdf",
        help="import and index a local PDF for one citation key",
    )
    import_pdf.add_argument("run_id")
    import_pdf.add_argument("citation_key")
    import_pdf.add_argument("pdf_path", type=Path)

    export = commands.add_parser("export", help="create a reproducible audit ZIP")
    export.add_argument("run_id")
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--no-pdfs", action="store_true")

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

    commands.add_parser("doctor", help="check local installation and configuration")
    commands.add_parser("plugins", help="list registered provider and agent plugins")

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


def _doctor_report(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
) -> tuple[int, dict[str, object]]:
    checks: list[dict[str, object]] = []

    def checked(name: str, operation: Any) -> None:
        try:
            detail = operation()
        except Exception as exc:
            checks.append({"name": name, "status": "error", "detail": str(exc)})
        else:
            checks.append({"name": name, "status": "ok", "detail": detail})

    checked("database", lambda: str(store.path.expanduser().resolve()))

    artifact_root = Path(artifact_root).expanduser().resolve()

    def check_artifacts() -> str:
        artifact_root.mkdir(parents=True, exist_ok=True)
        if not os.access(artifact_root, os.W_OK):
            raise PermissionError("artifact directory is not writable")
        return str(artifact_root)

    checked("artifacts", check_artifacts)
    checked(
        "default_corpus",
        lambda: f"{len(load_papers(_default_corpus_path()))} verified seed papers",
    )
    checked(
        "agent_configuration",
        lambda: AgentRuntimeConfig.from_env().active_backend,
    )
    checked(
        "provider_plugins",
        lambda: ", ".join(build_provider_registry().names()),
    )
    checked(
        "agent_plugins",
        lambda: ", ".join(build_agent_factory().manifest()),
    )
    status = "ok" if all(item["status"] == "ok" for item in checks) else "error"
    return (0 if status == "ok" else 2), {
        "status": status,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "checks": checks,
    }


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
        if args.command == "doctor":
            code, report = _doctor_report(store, args.artifacts)
            _print_json(report, stream=sys.stdout if code == 0 else sys.stderr)
            return code
        if args.command == "plugins":
            _print_json(
                {
                    "providers": list(build_provider_registry().options()),
                    "agents": build_agent_factory().manifest(),
                }
            )
            return 0
        if args.command == "status":
            _print_json(store.get_run(args.run_id).to_dict())
            return 0
        if args.command == "list":
            _print_json([run.to_dict() for run in store.list_runs()])
            return 0
        if args.command == "events":
            _print_json([event.to_dict() for event in store.list_events(args.run_id)])
            return 0
        if args.command == "discovery-attempts":
            _print_json(
                [
                    attempt.to_dict()
                    for attempt in store.list_discovery_attempts(args.run_id)
                ]
            )
            return 0
        if args.command == "documents":
            _print_json(
                [item.to_dict() for item in store.list_documents(args.run_id)]
            )
            return 0
        if args.command == "claims":
            _print_json([item.to_dict() for item in store.list_claims(args.run_id)])
            return 0
        if args.command == "evidence":
            _print_json(
                [
                    item.to_dict()
                    for item in store.list_claim_verifications(args.run_id)
                ]
            )
            return 0
        if args.command == "evidence-decide":
            run = store.get_run(args.run_id)
            if run.current_stage != WorkflowStage.AWAITING_EVIDENCE_REVIEW:
                raise ValueError("evidence decisions require the evidence review gate")
            if not args.reason.strip():
                raise ValueError("decision reason must be nonblank")
            claim_results = [
                item
                for item in store.list_claim_verifications(args.run_id)
                if item.claim_id == args.claim_id and item.blocking
            ]
            if not claim_results:
                raise ValueError("claim has no blocking verification result")
            if args.action == "accept_risk" and any(
                item.status != VerificationStatus.FULL_TEXT_UNAVAILABLE
                for item in claim_results
            ):
                raise ValueError(
                    "accept_risk is allowed only for unavailable full text"
                )
            decision = EvidenceReviewDecision.create(
                args.run_id,
                args.claim_id,
                args.action,
                args.reason.strip(),
                "human-cli",
            )
            store.put_evidence_review_decision(decision)
            _print_json(decision.to_dict())
            return 0
        if args.command == "import-pdf":
            document = DocumentImportService(
                store,
                LocalArtifactStore(args.artifacts),
            ).import_pdf(
                args.run_id,
                args.citation_key,
                args.pdf_path,
            )
            _print_json(document.to_dict())
            return 0
        if args.command == "export":
            _print_json(
                export_audit_bundle(
                    store,
                    LocalArtifactStore(args.artifacts),
                    args.run_id,
                    args.output,
                    include_pdfs=not args.no_pdfs,
                )
            )
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
                    query_texts = load_resume_query_texts(
                        artifact_store,
                        args.run_id,
                    )
                    full_text_enabled = load_resume_full_text(
                        artifact_store,
                        args.run_id,
                    )
                    engine = build_engine(
                        store,
                        args.artifacts,
                        discovery_enabled=enabled,
                        providers=providers,
                        max_results=max_results,
                        query_texts=query_texts,
                        full_text_enabled=full_text_enabled,
                    )
                    run = engine.resume(args.run_id)
            finally:
                reservation.release()
            _print_json(run.to_dict())
            return 0

        if args.command == "start":
            if len(args.query) > 8:
                _print_json(
                    {"error": "invalid_request", "message": "at most 8 queries are allowed"},
                    stream=sys.stderr,
                )
                return 2
            engine = build_engine(
                store,
                args.artifacts,
                discovery_enabled=args.discover,
                full_text_enabled=args.full_text,
                providers=tuple(args.providers),
                max_results=args.max_results,
                query_texts=tuple(args.query),
            )
            run = engine.start(args.topic, args.corpus)
        elif args.command == "retry-discovery":
            if len(args.query) > 8:
                _print_json(
                    {"error": "invalid_request", "message": "at most 8 queries are allowed"},
                    stream=sys.stderr,
                )
                return 2
            reservation = ActivityCoordinator.for_artifact_root(
                args.artifacts
            ).reserve_resume(args.run_id)
            try:
                with reservation.activate():
                    run = retry_discovery(
                        store,
                        args.artifacts,
                        args.run_id,
                        providers=tuple(args.providers),
                        max_results=args.max_results,
                        query_texts=tuple(args.query),
                    )
            finally:
                reservation.release()
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
    except (ProviderPluginError, AgentPluginError) as exc:
        _print_json(
            {"error": "plugin_configuration_error", "message": str(exc)},
            stream=sys.stderr,
        )
        return 2
    except (FileNotFoundError, ValueError) as exc:
        _print_json(
            {"error": "invalid_request", "message": str(exc)},
            stream=sys.stderr,
        )
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


def workbench_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="literature-review-workbench")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--db", type=Path, default=Path(".review-workflow/workflow.db"))
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path(".review-workflow/artifacts"),
    )
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default="127.0.0.1",
    )
    parser.add_argument("--port", type=_port_number, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    translated = [
        "--db",
        str(args.db),
        "--artifacts",
        str(args.artifacts),
        "ui",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.no_browser:
        translated.append("--no-browser")
    return main(translated)


__all__ = ["main", "run_workbench", "workbench_main"]
