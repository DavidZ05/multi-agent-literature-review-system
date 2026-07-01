from __future__ import annotations

from collections.abc import Mapping
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from src.literature_review.models import CandidateStatus
from src.literature_review.storage import (
    CandidateNotFoundError,
    RunNotFoundError,
)
from src.literature_review.workbench.jobs import (
    DuplicateResumeJobError,
    JobNotFoundError,
    StartRunRequest,
    WorkflowJobManager,
)
from src.literature_review.workbench.service import (
    PendingCandidatesError,
    WorkbenchService,
)


MAX_JSON_BODY_BYTES = 1024 * 1024


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
    ) -> None:
        if not isinstance(host, str) or host.lower() not in {
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError("host must be a loopback hostname or address")
        host = host.lower()
        self.workbench_service = service
        self.job_manager = job_manager
        self.mutation_token = (
            secrets.token_urlsafe() if mutation_token is None else mutation_token
        )
        if not isinstance(self.mutation_token, str) or not self.mutation_token:
            raise ValueError("mutation_token must be a nonempty string")
        self.static_root = None if static_root is None else Path(static_root)
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


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server: WorkbenchHTTPServer

    def do_GET(self) -> None:
        self._handle(self._dispatch_get)

    def do_POST(self) -> None:
        self._handle(self._dispatch_post)

    def do_DELETE(self) -> None:
        self._send_not_found()

    def do_HEAD(self) -> None:
        self._send_not_found(include_body=False)

    def do_OPTIONS(self) -> None:
        self._send_not_found()

    def do_PATCH(self) -> None:
        self._send_not_found()

    def do_PUT(self) -> None:
        self._send_not_found()

    def do_TRACE(self) -> None:
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
            and segments[3] in {"resume", "cancel", "close-discovery"}
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

    def _start_run(self, body: Mapping[str, object]) -> dict[str, object]:
        self._require_fields(
            body,
            {"topic", "corpus_path", "discover", "providers", "max_results"},
        )
        request = StartRunRequest(
            topic=body["topic"],  # type: ignore[arg-type]
            corpus_path=body["corpus_path"],  # type: ignore[arg-type]
            discovery_enabled=body["discover"],  # type: ignore[arg-type]
            providers=body["providers"],  # type: ignore[arg-type]
            max_results=body["max_results"],  # type: ignore[arg-type]
        )
        return self.server.job_manager.submit_start(request)

    def _run_action(
        self,
        run_id: str,
        action: str,
        body: Mapping[str, object],
    ) -> tuple[int, object]:
        self._require_fields(body, set())
        if action == "resume":
            return 202, self.server.job_manager.submit_resume(run_id)
        if action == "cancel":
            return 200, self.server.workbench_service.cancel_run(run_id)
        if action == "close-discovery":
            return 200, self.server.workbench_service.close_discovery(run_id)
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
        if self.headers.get("Transfer-Encoding") is not None:
            raise _APIError(400, "invalid_request", "Request body is invalid.")
        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length) if content_length is not None else -1
        except ValueError as exc:
            raise _APIError(
                400,
                "invalid_request",
                "Request body is invalid.",
            ) from exc
        if length < 0:
            raise _APIError(400, "invalid_request", "Request body is invalid.")
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


def create_workbench_server(
    service: WorkbenchService,
    job_manager: WorkflowJobManager,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    mutation_token: str | None = None,
    static_root: Path | None = None,
) -> WorkbenchHTTPServer:
    return WorkbenchHTTPServer(
        service,
        job_manager,
        host=host,
        port=port,
        mutation_token=mutation_token,
        static_root=static_root,
    )


__all__ = [
    "MAX_JSON_BODY_BYTES",
    "WorkbenchHTTPServer",
    "WorkbenchRequestHandler",
    "create_workbench_server",
]
