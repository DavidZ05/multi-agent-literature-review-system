from __future__ import annotations

from collections.abc import Mapping
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from src.literature_review.activity import RunBusy, RunDeletionBusy
from src.literature_review.models import CandidateStatus
from src.literature_review.storage import (
    CandidateDecisionNotAllowedError,
    CandidateNotFoundError,
    LocalArtifactStore,
    RunNotFoundError,
)
from src.literature_review.workbench.jobs import (
    DuplicateResumeJobError,
    JobNotFoundError,
    RetryDiscoveryRequest,
    StartRunRequest,
    WorkflowJobManager,
)
from src.literature_review.workbench.service import (
    PendingCandidatesError,
    RunDeletionConflictError,
    RunNotDeletableError,
    WorkbenchService,
)


MAX_JSON_BODY_BYTES = 1024 * 1024
_DEFAULT_STATIC_ROOT = Path(__file__).with_name("static")
_STATIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
_CONFIG_MARKER = b"__WORKBENCH_CONFIG__"


class _APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        **fields: object,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        super().__init__(message)

    def payload(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                **self.fields,
            }
        }


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        service: WorkbenchService,
        job_manager: WorkflowJobManager,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        mutation_token: str | None = None,
        static_root: Path | None = None,
        default_corpus_path: Path | None = None,
    ) -> None:
        if not isinstance(host, str) or host.lower() not in {
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError("host must be a loopback hostname or address")
        host = host.lower()
        service_artifact_root = Path(service.artifact_root).expanduser().resolve()
        manager_artifact_root = Path(job_manager.artifact_root).expanduser().resolve()
        if service_artifact_root != manager_artifact_root:
            raise ValueError(
                "workbench service and job manager artifact roots must match"
            )
        self.workbench_service = service
        self.job_manager = job_manager
        self.mutation_token = (
            secrets.token_urlsafe() if mutation_token is None else mutation_token
        )
        if not isinstance(self.mutation_token, str) or not self.mutation_token:
            raise ValueError("mutation_token must be a nonempty string")
        self.static_root = (
            _DEFAULT_STATIC_ROOT if static_root is None else Path(static_root)
        )
        self.default_corpus_path = (
            None
            if default_corpus_path is None
            else str(Path(default_corpus_path))
        )
        self.database_path = str(service.store.path.expanduser().resolve())
        self.artifact_root = str(manager_artifact_root)
        super().__init__((host, port), WorkbenchRequestHandler)

    @property
    def allowed_origins(self) -> frozenset[str]:
        port = self.server_address[1]
        return frozenset(
            {
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            }
        )

    @property
    def allowed_hosts(self) -> frozenset[str]:
        port = self.server_address[1]
        return frozenset(
            {
                "127.0.0.1",
                "localhost",
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            }
        )


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server: WorkbenchHTTPServer

    def do_GET(self) -> None:
        if not self._require_allowed_host():
            return
        request_path = urlsplit(self.path).path
        if request_path in _STATIC_ASSETS:
            self._serve_static(request_path)
            return
        if self._serve_run_download():
            return
        self._handle(self._dispatch_get)

    def do_POST(self) -> None:
        if not self._require_allowed_host():
            return
        self._handle(self._dispatch_post)

    def do_DELETE(self) -> None:
        if not self._require_allowed_host():
            return
        self._handle(self._dispatch_delete)

    def do_HEAD(self) -> None:
        if not self._require_allowed_host(include_body=False):
            return
        self._send_not_found(include_body=False)

    def do_OPTIONS(self) -> None:
        if not self._require_allowed_host():
            return
        self._send_not_found()

    def do_PATCH(self) -> None:
        if not self._require_allowed_host():
            return
        self._send_not_found()

    def do_PUT(self) -> None:
        if not self._require_allowed_host():
            return
        self._send_not_found()

    def do_TRACE(self) -> None:
        if not self._require_allowed_host():
            return
        self._send_not_found()

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        include_body = self.command != "HEAD"
        if int(code) == 501:
            self._send_error(
                501,
                "unsupported_method",
                "The requested method is not supported.",
                include_body=include_body,
            )
            return
        self._send_error(
            int(code),
            "http_error",
            "The HTTP request could not be processed.",
            include_body=include_body,
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle(self, operation: Any) -> None:
        try:
            status, payload = operation()
        except _APIError as exc:
            self._send_json(exc.status, exc.payload())
        except (RunNotFoundError, CandidateNotFoundError, JobNotFoundError):
            self._send_error(404, "not_found", "The requested resource was not found.")
        except PendingCandidatesError as exc:
            self._send_error(
                409,
                "pending_candidates",
                "Pending candidates must be resolved first.",
                pending_count=exc.pending_count,
            )
        except CandidateDecisionNotAllowedError as exc:
            self._send_error(
                409,
                "approval_not_allowed",
                "Candidate decisions are only allowed at the approval gate.",
                run_id=exc.run_id,
                candidate_id=exc.candidate_id,
            )
        except RunNotDeletableError as exc:
            self._send_error(
                409,
                "run_not_deletable",
                "The run cannot be deleted in its current state.",
                run_id=exc.run_id,
                run_status=exc.status.value,
            )
        except RunDeletionConflictError as exc:
            self._send_error(
                409,
                "run_deletion_conflict",
                "The run changed state during deletion.",
                run_id=exc.run_id,
                expected_status=exc.expected_status.value,
                actual_status=exc.actual_status.value,
            )
        except RunBusy as exc:
            self._send_error(
                409,
                "run_busy",
                "The run has workflow activity in progress.",
                run_id=exc.run_id,
            )
        except RunDeletionBusy as exc:
            self._send_error(
                409,
                "run_deletion_busy",
                "Artifact deletion is in progress.",
                run_id=exc.run_id,
            )
        except DuplicateResumeJobError as exc:
            self._send_error(
                409,
                "duplicate_resume_job",
                "A resume job is already active for this run.",
                existing_job_id=exc.existing_job_id,
            )
        except (KeyError, TypeError, ValueError):
            self._send_error(400, "invalid_request", "Request validation failed.")
        except Exception:
            self._send_error(
                500,
                "internal_error",
                "An internal server error occurred.",
            )
        else:
            self._send_json(status, payload)

    def _dispatch_get(self) -> tuple[int, object]:
        segments, query = self._request_target()
        service = self.server.workbench_service
        manager = self.server.job_manager

        if segments == ["api", "runs"] and not query:
            return 200, service.list_runs()
        if len(segments) == 3 and segments[:2] == ["api", "runs"] and not query:
            return 200, service.get_run_detail(segments[2])
        if (
            len(segments) == 4
            and segments[:2] == ["api", "runs"]
            and segments[3] == "events"
            and not query
        ):
            return 200, service.get_run_detail(segments[2])["events"]
        if (
            len(segments) == 4
            and segments[:2] == ["api", "runs"]
            and segments[3] == "candidates"
        ):
            status = self._candidate_status(query)
            return 200, service.list_candidates(segments[2], status)
        if (
            len(segments) == 3
            and segments[:2] == ["api", "jobs"]
            and not query
        ):
            return 200, manager.get_job(segments[2])
        if segments == ["api", "jobs"]:
            if query == {"status": ["active"]}:
                return 200, manager.list_jobs(active_only=True)
            if not query:
                return 200, manager.list_jobs()
            raise _APIError(400, "invalid_request", "Request validation failed.")
        raise _APIError(404, "not_found", "The requested resource was not found.")

    def _dispatch_post(self) -> tuple[int, object]:
        self._require_mutation_access()
        segments, query = self._request_target()
        if query:
            raise _APIError(400, "invalid_request", "Request validation failed.")

        if segments == ["api", "runs"]:
            body = self._read_json_body()
            return 202, self._start_run(body)
        if (
            len(segments) == 4
            and segments[:2] == ["api", "runs"]
            and segments[3]
            in {
                "resume",
                "cancel",
                "close-discovery",
                "retry-discovery",
                "evidence-decision",
                "import-pdf",
                "export",
            }
        ):
            body = self._read_json_body()
            return self._run_action(segments[2], segments[3], body)
        if (
            len(segments) == 6
            and segments[:2] == ["api", "runs"]
            and segments[3] == "candidates"
            and segments[5] in {"approve", "reject", "defer"}
        ):
            body = self._read_json_body()
            return self._candidate_action(
                segments[2],
                segments[4],
                segments[5],
                body,
            )
        raise _APIError(404, "not_found", "The requested resource was not found.")

    def _dispatch_delete(self) -> tuple[int, object]:
        segments, query = self._request_target()
        parsed = urlsplit(self.path)
        if (
            len(segments) == 3
            and segments[:2] == ["api", "runs"]
            and not query
            and not parsed.fragment
            and parsed.path == f"/api/runs/{segments[2]}"
        ):
            self._require_mutation_access()
            self._require_empty_body()
            return 200, self.server.workbench_service.delete_run(segments[2])
        raise _APIError(404, "not_found", "The requested resource was not found.")

    def _start_run(self, body: Mapping[str, object]) -> dict[str, object]:
        required = {"topic", "corpus_path", "discover", "providers", "max_results"}
        optional = {"queries", "full_text"}
        if not required <= set(body) or set(body) - required - optional:
            raise _APIError(400, "invalid_request", "Request validation failed.")
        request = StartRunRequest(
            topic=body["topic"],  # type: ignore[arg-type]
            corpus_path=body["corpus_path"],  # type: ignore[arg-type]
            discovery_enabled=body["discover"],  # type: ignore[arg-type]
            full_text_enabled=body.get("full_text", False),  # type: ignore[arg-type]
            providers=body["providers"],  # type: ignore[arg-type]
            max_results=body["max_results"],  # type: ignore[arg-type]
            query_texts=body.get("queries", ()),  # type: ignore[arg-type]
        )
        return self.server.job_manager.submit_start(request)

    def _run_action(
        self,
        run_id: str,
        action: str,
        body: Mapping[str, object],
    ) -> tuple[int, object]:
        if action == "resume":
            self._require_fields(body, set())
            return 202, self.server.job_manager.submit_resume(run_id)
        if action == "retry-discovery":
            self._require_fields(body, {"providers", "max_results", "queries"})
            return 202, self.server.job_manager.submit_discovery_retry(
                RetryDiscoveryRequest(
                    run_id=run_id,
                    providers=body["providers"],  # type: ignore[arg-type]
                    max_results=body["max_results"],  # type: ignore[arg-type]
                    query_texts=body["queries"],  # type: ignore[arg-type]
                )
            )
        if action == "cancel":
            self._require_fields(body, set())
            return 200, self.server.workbench_service.cancel_run(run_id)
        if action == "close-discovery":
            self._require_fields(body, set())
            return 200, self.server.workbench_service.close_discovery(run_id)
        if action == "evidence-decision":
            self._require_fields(body, {"claim_id", "action", "reason"})
            return 200, self.server.workbench_service.decide_evidence(
                run_id,
                self._string_field(body, "claim_id"),
                self._string_field(body, "action"),
                self._string_field(body, "reason"),
            )
        if action == "import-pdf":
            self._require_fields(body, {"citation_key", "pdf_path"})
            return 200, self.server.workbench_service.import_pdf(
                run_id,
                self._string_field(body, "citation_key"),
                self._string_field(body, "pdf_path"),
            )
        if action == "export":
            self._require_fields(body, {"include_pdfs"})
            include_pdfs = body["include_pdfs"]
            if not isinstance(include_pdfs, bool):
                raise ValueError("include_pdfs must be a boolean")
            return 200, self.server.workbench_service.export_run(
                run_id,
                include_pdfs=include_pdfs,
            )
        raise _APIError(404, "not_found", "The requested resource was not found.")

    def _candidate_action(
        self,
        run_id: str,
        candidate_id: str,
        action: str,
        body: Mapping[str, object],
    ) -> tuple[int, object]:
        service = self.server.workbench_service
        if action == "approve":
            self._require_fields(
                body,
                {"reason", "category", "contribution", "tags"},
            )
            reason = self._string_field(body, "reason")
            category = self._string_field(body, "category")
            contribution = self._string_field(body, "contribution")
            tags = body["tags"]
            if not isinstance(tags, list) or not all(
                isinstance(tag, str) for tag in tags
            ):
                raise ValueError("tags must be a list of strings")
            return 200, service.approve_candidate(
                run_id,
                candidate_id,
                reason,
                category,
                contribution,
                tags,
            )
        if action in {"reject", "defer"}:
            self._require_fields(body, {"reason"})
            reason = self._string_field(body, "reason")
            operation = (
                service.reject_candidate
                if action == "reject"
                else service.defer_candidate
            )
            return 200, operation(run_id, candidate_id, reason)
        raise _APIError(404, "not_found", "The requested resource was not found.")

    def _require_mutation_access(self) -> None:
        tokens = self.headers.get_all("X-Workbench-Token", [])
        if len(tokens) != 1 or not hmac.compare_digest(
            tokens[0],
            self.server.mutation_token,
        ):
            raise _APIError(403, "forbidden", "Mutation access was denied.")

        origins = self.headers.get_all("Origin", [])
        if not origins:
            return
        if len(origins) != 1 or self._normalize_origin(origins[0]) not in (
            self.server.allowed_origins
        ):
            raise _APIError(403, "forbidden", "Mutation access was denied.")

    def _require_allowed_host(self, *, include_body: bool = True) -> bool:
        hosts = self.headers.get_all("Host", [])
        if (
            len(hosts) == 1
            and hosts[0].isascii()
            and hosts[0].strip().lower() in self.server.allowed_hosts
        ):
            return True
        self._send_error(
            421,
            "misdirected_request",
            "The request Host is not accepted by this local Workbench.",
            include_body=include_body,
        )
        return False

    @staticmethod
    def _normalize_origin(origin: str) -> str | None:
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme.lower() != "http"
            or parsed.hostname is None
            or port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return None
        return f"http://{parsed.hostname.lower()}:{port}"

    def _read_json_body(self) -> Mapping[str, object]:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise _APIError(
                415,
                "unsupported_media_type",
                "Content-Type must be application/json.",
            )
        if self.headers.get_all("Transfer-Encoding", []):
            raise _APIError(400, "invalid_request", "Request body is invalid.")
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) != 1:
            raise _APIError(400, "invalid_request", "Request body is invalid.")
        content_length = content_lengths[0]
        if (
            not content_length
            or not content_length.isascii()
            or not content_length.isdigit()
            or (len(content_length) > 1 and content_length.startswith("0"))
        ):
            raise _APIError(400, "invalid_request", "Request body is invalid.")
        length = int(content_length)
        if length > MAX_JSON_BODY_BYTES:
            raise _APIError(
                413,
                "payload_too_large",
                "Request body exceeds the 1 MiB limit.",
            )
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _APIError(
                400,
                "invalid_json",
                "Request body must contain valid JSON.",
            ) from exc
        if not isinstance(value, dict):
            raise _APIError(
                400,
                "invalid_request",
                "Request body must be a JSON object.",
            )
        return value

    def _require_empty_body(self) -> None:
        if self.headers.get_all("Transfer-Encoding", []):
            raise _APIError(400, "invalid_request", "Request body is invalid.")
        content_lengths = self.headers.get_all("Content-Length", [])
        if not content_lengths:
            return
        if len(content_lengths) != 1 or content_lengths[0] != "0":
            raise _APIError(400, "invalid_request", "Request body is invalid.")

    def _request_target(self) -> tuple[list[str], dict[str, list[str]]]:
        parsed = urlsplit(self.path)
        try:
            segments = [
                unquote(segment, encoding="utf-8", errors="strict")
                for segment in parsed.path.split("/")
                if segment
            ]
        except UnicodeDecodeError as exc:
            raise _APIError(
                400,
                "invalid_request",
                "Request target is invalid.",
            ) from exc
        return segments, parse_qs(parsed.query, keep_blank_values=True)

    @staticmethod
    def _candidate_status(
        query: dict[str, list[str]],
    ) -> CandidateStatus | None:
        if not query:
            return None
        if set(query) != {"status"} or len(query["status"]) != 1:
            raise _APIError(400, "invalid_request", "Request validation failed.")
        try:
            return CandidateStatus(query["status"][0])
        except ValueError as exc:
            raise _APIError(
                400,
                "invalid_request",
                "Request validation failed.",
            ) from exc

    @staticmethod
    def _require_fields(
        body: Mapping[str, object],
        expected: set[str],
    ) -> None:
        if set(body) != expected:
            raise _APIError(400, "invalid_request", "Request validation failed.")

    @staticmethod
    def _string_field(body: Mapping[str, object], name: str) -> str:
        value = body[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonblank string")
        return value

    def _send_not_found(self, *, include_body: bool = True) -> None:
        self._send_error(
            404,
            "not_found",
            "The requested resource was not found.",
            include_body=include_body,
        )

    def _send_error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        include_body: bool = True,
        **fields: object,
    ) -> None:
        self._send_json(
            status,
            {"error": {"code": code, "message": message, **fields}},
            include_body=include_body,
        )

    def _send_json(
        self,
        status: int,
        payload: object,
        *,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _serve_static(self, request_path: str) -> None:
        filename, content_type = _STATIC_ASSETS[request_path]
        try:
            body = (self.server.static_root / filename).read_bytes()
            if request_path == "/":
                body = self._inject_workbench_config(body)
        except (OSError, ValueError):
            self._send_not_found()
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _serve_run_download(self) -> bool:
        try:
            segments, query = self._request_target()
        except _APIError:
            return False
        if (
            len(segments) != 5
            or segments[:2] != ["api", "runs"]
            or segments[3] != "download"
            or query
            or segments[4] not in {"survey", "audit"}
        ):
            return False
        run_id = segments[2]
        try:
            self.server.workbench_service.store.get_run(run_id)
            artifact_store = LocalArtifactStore(
                self.server.workbench_service.artifact_root
            )
            if segments[4] == "survey":
                path = artifact_store.path_for(run_id, "final/survey.md")
                content_type = "text/markdown; charset=utf-8"
                filename = f"{run_id}-survey.md"
            else:
                path = artifact_store.path_for(
                    run_id,
                    f"exports/{run_id}-audit.zip",
                )
                content_type = "application/zip"
                filename = f"{run_id}-audit.zip"
            body = path.read_bytes()
        except (FileNotFoundError, RunNotFoundError, ValueError):
            self._send_not_found()
            return True
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _inject_workbench_config(self, template: bytes) -> bytes:
        if template.count(_CONFIG_MARKER) != 1:
            raise ValueError("index template must contain one config marker")
        config = json.dumps(
            {
                "mutationToken": self.server.mutation_token,
                "defaultCorpusPath": self.server.default_corpus_path,
                "databasePath": self.server.database_path,
                "artifactRoot": self.server.artifact_root,
                "providers": list(self.server.job_manager.provider_options),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        safe_config = (
            config.replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )
        return template.replace(_CONFIG_MARKER, safe_config.encode("ascii"))


def create_workbench_server(
    service: WorkbenchService,
    job_manager: WorkflowJobManager,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    mutation_token: str | None = None,
    static_root: Path | None = None,
    default_corpus_path: Path | None = None,
) -> WorkbenchHTTPServer:
    return WorkbenchHTTPServer(
        service,
        job_manager,
        host=host,
        port=port,
        mutation_token=mutation_token,
        static_root=static_root,
        default_corpus_path=default_corpus_path,
    )


__all__ = [
    "MAX_JSON_BODY_BYTES",
    "WorkbenchHTTPServer",
    "WorkbenchRequestHandler",
    "create_workbench_server",
]
