from concurrent.futures import Future
from dataclasses import replace
import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest

from src.literature_review.activity import RunBusy, RunDeletionBusy
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workbench import (
    RunDeletionConflictError,
    RunNotDeletableError,
    WorkbenchService,
    WorkflowJobManager,
    create_workbench_server,
)


class ManualExecutor:
    def __init__(self) -> None:
        self.futures: list[Future[object]] = []
        self.shutdown_calls: list[bool] = []

    def submit(self, function: object, *args: object) -> Future[object]:
        future: Future[object] = Future()
        self.futures.append(future)
        return future

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


def candidate(candidate_id: str = "cand_pending") -> CandidatePaper:
    return CandidatePaper(
        candidate_id=candidate_id,
        title="Pending paper",
        authors=("Ada Researcher",),
        year=2026,
        venue="Test Conference",
        abstract="A candidate for HTTP testing.",
        doi=None,
        arxiv_id="2601.00001",
        semantic_scholar_id=None,
        source_urls=("https://example.test/paper",),
        open_access_pdf_url=None,
        provenance=("test:http",),
        recommendation=ScreeningRecommendation.REVIEW,
        relevance_score=0.5,
        status=CandidateStatus.PENDING,
    )


class WorkbenchHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.run = ResearchRun.create("HTTP workbench")
        self.store.create_run(self.run)
        self.pending = candidate()
        self.store.upsert_candidate(self.run.run_id, self.pending)
        self.event = self.store.append_event(
            self.run.run_id,
            "candidate_discovered",
            {"candidate_id": self.pending.candidate_id},
            WorkflowStage.DISCOVERING,
        )
        self.corpus_path = root / "corpus.json"
        self.corpus_path.write_text("[]", encoding="utf-8")
        self.executor = ManualExecutor()
        self.manager = WorkflowJobManager(
            self.store,
            root / "artifacts",
            executor=self.executor,
        )
        self.service = WorkbenchService(
            self.store,
            cancel=lambda run_id: self.store.get_run(run_id),
            artifact_root=self.manager.artifact_root,
        )
        self.token = "test-mutation-token"
        self.server = create_workbench_server(
            self.service,
            self.manager,
            host="127.0.0.1",
            port=0,
            mutation_token=self.token,
            default_corpus_path=self.corpus_path,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.manager.shutdown(wait=False)
        self.tmp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: object | bytes | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], object]:
        request_headers = dict(headers or {})
        payload: bytes | None
        if isinstance(body, bytes):
            payload = body
        elif body is None:
            payload = None
        else:
            payload = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            return (
                response.status,
                response_headers,
                None if not raw else json.loads(raw),
            )
        finally:
            connection.close()

    def request_bytes(
        self,
        method: str,
        path: str,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            body = response.read()
            headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            return response.status, headers, body
        finally:
            connection.close()

    def mutation_headers(self, **extra: str) -> dict[str, str]:
        return {"X-Workbench-Token": self.token, **extra}

    def prepare_approval_gate(self) -> None:
        self.run = replace(
            self.run,
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(self.run)

    def raw_post(
        self,
        framing_headers: tuple[str, ...],
        body: bytes = b"{}",
    ) -> tuple[int, dict[str, str], object]:
        request = (
            (
                f"POST /api/runs/{self.run.run_id}/cancel HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                f"X-Workbench-Token: {self.token}\r\n"
                "Content-Type: application/json\r\n"
                + "".join(f"{header}\r\n" for header in framing_headers)
                + "Connection: close\r\n\r\n"
            ).encode("ascii")
            + body
        )
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as client:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while chunk := client.recv(65536):
                chunks.append(chunk)

        header_block, response_body = b"".join(chunks).split(b"\r\n\r\n", 1)
        lines = header_block.decode("ascii").split("\r\n")
        status = int(lines[0].split(" ", 2)[1])
        headers = {
            name.lower(): value.strip()
            for name, value in (line.split(":", 1) for line in lines[1:])
        }
        return status, headers, json.loads(response_body)

    def raw_delete(
        self,
        run_id: str,
        framing_headers: tuple[str, ...],
        body: bytes = b"",
    ) -> tuple[int, dict[str, str], object]:
        request = (
            (
                f"DELETE /api/runs/{run_id} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                f"X-Workbench-Token: {self.token}\r\n"
                + "".join(f"{header}\r\n" for header in framing_headers)
                + "Connection: close\r\n\r\n"
            ).encode("ascii")
            + body
        )
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as client:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while chunk := client.recv(65536):
                chunks.append(chunk)

        header_block, response_body = b"".join(chunks).split(b"\r\n\r\n", 1)
        lines = header_block.decode("ascii").split("\r\n")
        status = int(lines[0].split(" ", 2)[1])
        headers = {
            name.lower(): value.strip()
            for name, value in (line.split(":", 1) for line in lines[1:])
        }
        return status, headers, json.loads(response_body)

    def assert_json_headers(self, headers: dict[str, str]) -> None:
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertGreater(int(headers["content-length"]), 0)

    def test_read_route_families_return_service_and_job_payloads(self) -> None:
        accepted_status, _, accepted = self.request(
            "POST",
            "/api/runs",
            {
                "topic": "New topic",
                "corpus_path": str(self.corpus_path),
                "discover": False,
                "providers": ["arxiv"],
                "max_results": 4,
            },
            headers=self.mutation_headers(),
        )
        cases = (
            ("/api/runs", self.service.list_runs()),
            (f"/api/runs/{self.run.run_id}", self.service.get_run_detail(self.run.run_id)),
            (f"/api/runs/{self.run.run_id}/events", [self.event.to_dict()]),
            (
                f"/api/runs/{self.run.run_id}/candidates",
                [self.pending.to_dict()],
            ),
            (
                f"/api/runs/{self.run.run_id}/candidates?status=pending",
                [self.pending.to_dict()],
            ),
            ("/api/jobs", self.manager.list_jobs()),
            ("/api/jobs?status=active", self.manager.list_jobs(active_only=True)),
            (f"/api/jobs/{accepted['job_id']}", self.manager.get_job(accepted["job_id"])),
        )

        self.assertEqual(accepted_status, 202)
        for path, expected in cases:
            with self.subTest(path=path):
                status, headers, payload = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(payload, expected)
                self.assert_json_headers(headers)

    def test_survey_and_audit_downloads_use_fixed_run_artifacts(self) -> None:
        artifacts = LocalArtifactStore(self.manager.artifact_root)
        artifacts.write_text(
            self.run.run_id,
            "final/survey.md",
            "# Verified survey\n",
        )

        export_status, _, export_payload = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/export",
            {"include_pdfs": False},
            headers=self.mutation_headers(),
        )
        survey_status, survey_headers, survey_body = self.request_bytes(
            "GET",
            f"/api/runs/{self.run.run_id}/download/survey",
        )
        audit_status, audit_headers, audit_body = self.request_bytes(
            "GET",
            f"/api/runs/{self.run.run_id}/download/audit",
        )
        missing_status, _, _ = self.request_bytes(
            "GET",
            f"/api/runs/{self.run.run_id}/download/unknown",
        )

        self.assertEqual(export_status, 200)
        self.assertFalse(export_payload["include_pdfs"])
        self.assertEqual(survey_status, 200)
        self.assertEqual(survey_body, b"# Verified survey\n")
        self.assertEqual(
            survey_headers["content-type"],
            "text/markdown; charset=utf-8",
        )
        self.assertIn("attachment", survey_headers["content-disposition"])
        self.assertEqual(audit_status, 200)
        self.assertEqual(audit_headers["content-type"], "application/zip")
        self.assertTrue(audit_body.startswith(b"PK"))
        self.assertEqual(missing_status, 404)

    def test_candidate_status_filter_rejects_invalid_value(self) -> None:
        status, _, payload = self.request(
            "GET",
            f"/api/runs/{self.run.run_id}/candidates?status=unknown",
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request")

    def test_all_routes_reject_foreign_or_ambiguous_host_headers(self) -> None:
        status, _, payload = self.request(
            "GET",
            "/api/runs",
            headers={"Host": "attacker.example"},
        )

        self.assertEqual(status, 421)
        self.assertEqual(payload["error"]["code"], "misdirected_request")

        status, _, payload = self.raw_post(
            (
                "Host: attacker.example",
                "Content-Length: 2",
            )
        )
        self.assertEqual(status, 421)
        self.assertEqual(payload["error"]["code"], "misdirected_request")

        status, _, payload = self.request("GET", "/api/jobs?status=finished")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request")

    def test_start_and_resume_return_unmodified_accepted_jobs(self) -> None:
        status, _, start = self.request(
            "POST",
            "/api/runs",
            {
                "topic": "New topic",
                "corpus_path": str(self.corpus_path),
                "discover": True,
                "providers": ["semantic_scholar"],
                "max_results": 6,
            },
            headers=self.mutation_headers(),
        )
        resume_status, _, resume = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/resume",
            {},
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 202)
        self.assertEqual(
            set(start),
            {"job_id", "kind", "status", "equivalent_command"},
        )
        tracked_start = self.manager.get_job(start["job_id"])
        for key, value in start.items():
            self.assertEqual(tracked_start[key], value)
        self.assertEqual(resume_status, 202)
        self.assertEqual(resume["kind"], "resume")
        self.assertEqual(resume["status"], "queued")

    def test_discovery_retry_route_accepts_provider_query_controls(self) -> None:
        self.prepare_approval_gate()

        status, _, payload = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/retry-discovery",
            {
                "providers": ["arxiv"],
                "max_results": 9,
                "queries": ["agent memory benchmark"],
            },
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 202)
        self.assertEqual(payload["kind"], "discovery_retry")
        self.assertIn("retry-discovery", payload["equivalent_command"])
        self.assertIn("--providers=arxiv", payload["equivalent_command"])

    def test_run_and_candidate_mutation_route_families_return_service_payloads(
        self,
    ) -> None:
        self.prepare_approval_gate()
        cases = (
            ("approve", {
                "reason": "Strong evidence",
                "category": "memory",
                "contribution": "Adds a useful result",
                "tags": ["agents", "memory"],
            }),
            ("reject", {"reason": "Outside scope"}),
            ("defer", {"reason": "Needs full text"}),
        )
        for action, body in cases:
            with self.subTest(action=action):
                candidate_value = candidate(f"cand_{action}")
                self.store.upsert_candidate(self.run.run_id, candidate_value)
                status, _, payload = self.request(
                    "POST",
                    (
                        f"/api/runs/{self.run.run_id}/candidates/"
                        f"{candidate_value.candidate_id}/{action}"
                    ),
                    body,
                    headers=self.mutation_headers(),
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    payload["candidate"]["status"],
                    {
                        "approve": "approved",
                        "reject": "rejected",
                        "defer": "deferred",
                    }[action],
                )
                self.assertIn("decision", payload)
                self.assertIn("equivalent_command", payload)

        cancel_status, _, cancel = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/cancel",
            {},
            headers=self.mutation_headers(),
        )
        self.assertEqual(cancel_status, 200)
        self.assertEqual(cancel, self.service.cancel_run(self.run.run_id))

    def test_delete_exact_run_route_requires_no_body_and_returns_service_payload(
        self,
    ) -> None:
        completed = ResearchRun.create("Delete over HTTP")
        completed = completed.__class__.from_dict(
            {**completed.to_dict(), "status": RunStatus.COMPLETED.value}
        )
        self.store.create_run(completed)
        artifact = (
            self.manager.artifact_root
            / "runs"
            / completed.run_id
            / "result.txt"
        )
        artifact.parent.mkdir(parents=True)
        artifact.write_text("delete", encoding="utf-8")

        status, headers, payload = self.request(
            "DELETE",
            f"/api/runs/{completed.run_id}",
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["run_id"], completed.run_id)
        self.assertEqual(payload["status"], "deleted")
        self.assertFalse(artifact.exists())
        self.assert_json_headers(headers)

    def test_delete_rejects_request_body_without_deleting_run(self) -> None:
        completed = ResearchRun.create("Reject DELETE body")
        completed = completed.__class__.from_dict(
            {**completed.to_dict(), "status": RunStatus.COMPLETED.value}
        )
        self.store.create_run(completed)

        status, _, payload = self.request(
            "DELETE",
            f"/api/runs/{completed.run_id}",
            {"unexpected": True},
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(self.store.get_run(completed.run_id), completed)

    def test_delete_rejects_ambiguous_or_transfer_encoded_framing(self) -> None:
        completed = ResearchRun.create("Reject DELETE framing")
        completed = completed.__class__.from_dict(
            {**completed.to_dict(), "status": RunStatus.COMPLETED.value}
        )
        self.store.create_run(completed)
        cases = (
            ("duplicate", ("Content-Length: 0", "Content-Length: 0")),
            ("comma_joined", ("Content-Length: 0, 0",)),
            ("transfer_encoding", ("Transfer-Encoding: chunked",)),
        )

        for name, framing_headers in cases:
            with self.subTest(name=name):
                status, headers, payload = self.raw_delete(
                    completed.run_id,
                    framing_headers,
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_request")
                self.assert_json_headers(headers)

        self.assertEqual(self.store.get_run(completed.run_id), completed)

    def test_delete_requires_exact_token_and_allows_only_bound_origin(self) -> None:
        path = f"/api/runs/{self.run.run_id}"
        cases = (
            ({}, 403),
            ({"X-Workbench-Token": f"{self.token}x"}, 403),
            (
                self.mutation_headers(
                    Origin=f"http://localhost:{self.port + 1}"
                ),
                403,
            ),
            (
                self.mutation_headers(
                    Origin=f"http://localhost:{self.port}"
                ),
                409,
            ),
        )

        for headers, expected_status in cases:
            with self.subTest(headers=headers):
                status, _, payload = self.request(
                    "DELETE",
                    path,
                    headers=headers,
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(
                    payload["error"]["code"],
                    "forbidden" if expected_status == 403 else "run_not_deletable",
                )

    def test_delete_maps_domain_conflicts_to_stable_http_errors(self) -> None:
        cases = (
            (
                RunNotDeletableError(self.run.run_id, RunStatus.ACTIVE),
                "run_not_deletable",
            ),
            (
                RunDeletionConflictError(
                    self.run.run_id,
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                ),
                "run_deletion_conflict",
            ),
            (RunBusy(self.run.run_id), "run_busy"),
            (RunDeletionBusy(self.run.run_id), "run_deletion_busy"),
        )
        original_delete = self.service.delete_run
        try:
            for error, expected_code in cases:
                with self.subTest(code=expected_code):
                    def raise_error(run_id: str, error: Exception = error) -> object:
                        raise error

                    self.service.delete_run = raise_error  # type: ignore[method-assign]
                    status, _, payload = self.request(
                        "DELETE",
                        f"/api/runs/{self.run.run_id}",
                        headers=self.mutation_headers(),
                    )
                    self.assertEqual(status, 409)
                    self.assertEqual(payload["error"]["code"], expected_code)
                    if expected_code == "run_not_deletable":
                        self.assertEqual(
                            payload["error"]["run_status"],
                            RunStatus.ACTIVE.value,
                        )
        finally:
            self.service.delete_run = original_delete  # type: ignore[method-assign]

    def test_delete_unknown_and_nonexact_routes_return_not_found(self) -> None:
        unknown = "run_0123456789abcdef0123456789abcdef"
        paths = (
            f"/api/runs/{unknown}",
            f"/api/runs/{self.run.run_id}/",
            f"/api/runs/{self.run.run_id}/extra",
            "/api/runs",
            "/api/other/value",
        )
        for path in paths:
            with self.subTest(path=path):
                status, headers, payload = self.request(
                    "DELETE",
                    path,
                    headers=self.mutation_headers(),
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"]["code"], "not_found")
                self.assert_json_headers(headers)

    def test_unknown_delete_route_returns_not_found_before_authentication(
        self,
    ) -> None:
        status, headers, payload = self.request(
            "DELETE",
            "/api/unknown",
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assert_json_headers(headers)

    def test_close_discovery_returns_pending_conflict_then_service_payload(self) -> None:
        self.prepare_approval_gate()
        status, _, payload = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/close-discovery",
            {},
            headers=self.mutation_headers(),
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            payload,
            {
                "error": {
                    "code": "pending_candidates",
                    "message": "Pending candidates must be resolved first.",
                    "pending_count": 1,
                }
            },
        )

        self.service.reject_candidate(
            self.run.run_id,
            self.pending.candidate_id,
            "Not included",
        )
        status, _, payload = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/close-discovery",
            {},
            headers=self.mutation_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, self.service.close_discovery(self.run.run_id))

    def test_candidate_mutation_outside_approval_gate_returns_conflict(self) -> None:
        status, _, payload = self.request(
            "POST",
            (
                f"/api/runs/{self.run.run_id}/candidates/"
                f"{self.pending.candidate_id}/reject"
            ),
            {"reason": "Outside scope"},
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "approval_not_allowed")

    def test_duplicate_resume_exposes_only_existing_job_id(self) -> None:
        _, _, first = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/resume",
            {},
            headers=self.mutation_headers(),
        )
        status, _, payload = self.request(
            "POST",
            f"/api/runs/{self.run.run_id}/resume",
            {},
            headers=self.mutation_headers(),
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            payload,
            {
                "error": {
                    "code": "duplicate_resume_job",
                    "message": "A resume job is already active for this run.",
                    "existing_job_id": first["job_id"],
                }
            },
        )

    def test_mutations_require_exact_token(self) -> None:
        for headers in ({}, {"X-Workbench-Token": f"{self.token}x"}):
            with self.subTest(headers=headers):
                status, _, payload = self.request(
                    "POST",
                    f"/api/runs/{self.run.run_id}/cancel",
                    {},
                    headers=headers,
                )
                self.assertEqual(status, 403)
                self.assertEqual(payload["error"]["code"], "forbidden")

    def test_origin_allows_only_bound_loopback_origins(self) -> None:
        allowed = (
            f"http://127.0.0.1:{self.port}",
            f"http://localhost:{self.port}",
            f"HTTP://LOCALHOST:{self.port}/",
        )
        for origin in allowed:
            with self.subTest(origin=origin):
                status, _, _ = self.request(
                    "POST",
                    f"/api/runs/{self.run.run_id}/cancel",
                    {},
                    headers=self.mutation_headers(Origin=origin),
                )
                self.assertEqual(status, 200)

        rejected = (
            "https://localhost",
            f"http://localhost:{self.port + 1}",
            f"http://localhost:{self.port}@evil.test",
            "null",
        )
        for origin in rejected:
            with self.subTest(origin=origin):
                status, _, payload = self.request(
                    "POST",
                    f"/api/runs/{self.run.run_id}/cancel",
                    {},
                    headers=self.mutation_headers(Origin=origin),
                )
                self.assertEqual(status, 403)
                self.assertEqual(payload["error"]["code"], "forbidden")

    def test_server_rejects_non_loopback_bind_host(self) -> None:
        rejected_server = None
        try:
            rejected_server = create_workbench_server(
                self.service,
                self.manager,
                host="0.0.0.0",
                port=0,
                mutation_token=self.token,
            )
        except ValueError:
            pass
        else:
            self.fail("non-loopback bind host was accepted")
        finally:
            if rejected_server is not None:
                rejected_server.server_close()

    def test_server_rejects_mismatched_artifact_roots(self) -> None:
        other_service = WorkbenchService(
            self.store,
            artifact_root=Path(self.tmp.name) / "other-artifacts",
        )

        with self.assertRaises(ValueError):
            create_workbench_server(
                other_service,
                self.manager,
                host="127.0.0.1",
                port=0,
                mutation_token=self.token,
            )

    def test_server_accepts_supported_hosts_and_fixed_ports(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        fixed_port = probe.getsockname()[1]
        probe.close()

        servers = []
        try:
            servers.append(
                create_workbench_server(
                    self.service,
                    self.manager,
                    host="127.0.0.1",
                    port=fixed_port,
                    mutation_token=self.token,
                )
            )
            servers.append(
                create_workbench_server(
                    self.service,
                    self.manager,
                    host="localhost",
                    port=0,
                    mutation_token=self.token,
                )
            )
            self.assertEqual(servers[0].server_address[1], fixed_port)
            self.assertGreater(servers[1].server_address[1], 0)
        finally:
            for server in servers:
                server.server_close()

    def test_unsupported_methods_use_json_errors_and_head_has_no_body(self) -> None:
        for path in ("/api/runs", "/"):
            for method in ("OPTIONS", "TRACE"):
                with self.subTest(path=path, method=method):
                    status, headers, payload = self.request(method, path)
                    self.assertEqual(status, 404)
                    self.assertEqual(payload["error"]["code"], "not_found")
                    self.assert_json_headers(headers)

            with self.subTest(path=path, method="HEAD"):
                status, headers, payload = self.request("HEAD", path)
                self.assertEqual(status, 404)
                self.assertIsNone(payload)
                self.assert_json_headers(headers)

    def test_arbitrary_unsupported_methods_use_json_errors(self) -> None:
        for method in ("CONNECT", "BREW"):
            with self.subTest(method=method):
                status, headers, payload = self.request(method, "/api/runs")
                self.assertEqual(status, 501)
                self.assertEqual(
                    payload,
                    {
                        "error": {
                            "code": "unsupported_method",
                            "message": "The requested method is not supported.",
                        }
                    },
                )
                self.assert_json_headers(headers)

    def test_unknown_actions_return_not_found_before_body_validation(self) -> None:
        paths = (
            f"/api/runs/{self.run.run_id}/unknown",
            (
                f"/api/runs/{self.run.run_id}/candidates/"
                f"{self.pending.candidate_id}/unknown"
            ),
        )
        headers = self.mutation_headers(**{"Content-Type": "application/json"})
        for path in paths:
            with self.subTest(path=path):
                status, response_headers, payload = self.request(
                    "POST",
                    path,
                    b"{not-json",
                    headers=headers,
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"]["code"], "not_found")
                self.assert_json_headers(response_headers)

    def test_post_requires_json_and_valid_bounded_body(self) -> None:
        cases = (
            (
                b"{}",
                self.mutation_headers(**{"Content-Type": "text/plain"}),
                415,
                "unsupported_media_type",
            ),
            (
                b"{not-json",
                self.mutation_headers(**{"Content-Type": "application/json"}),
                400,
                "invalid_json",
            ),
            (
                b"",
                self.mutation_headers(
                    **{
                        "Content-Type": "application/json",
                        "Content-Length": str(1024 * 1024 + 1),
                    }
                ),
                413,
                "payload_too_large",
            ),
        )
        for body, headers, expected_status, code in cases:
            with self.subTest(code=code):
                status, _, payload = self.request(
                    "POST",
                    f"/api/runs/{self.run.run_id}/cancel",
                    body,
                    headers=headers,
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["error"]["code"], code)

    def test_ambiguous_or_unsupported_request_framing_is_rejected(self) -> None:
        mutation_calls = []
        original_cancel = self.service.cancel_run

        def tracked_cancel(run_id: str) -> dict[str, object]:
            mutation_calls.append(run_id)
            return original_cancel(run_id)

        self.service.cancel_run = tracked_cancel  # type: ignore[method-assign]
        cases = (
            ("duplicate_same", ("Content-Length: 2", "Content-Length: 2")),
            ("duplicate_conflicting", ("Content-Length: 2", "Content-Length: 3")),
            ("comma_joined", ("Content-Length: 2, 2",)),
            ("signed", ("Content-Length: +2",)),
            ("leading_zero", ("Content-Length: 02",)),
            ("negative", ("Content-Length: -1",)),
            ("trailing_space", ("Content-Length: 2 ",)),
            (
                "transfer_encoding",
                ("Content-Length: 2", "Transfer-Encoding: chunked"),
            ),
        )
        for name, framing_headers in cases:
            with self.subTest(name=name):
                status, headers, payload = self.raw_post(framing_headers)
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_request")
                self.assert_json_headers(headers)

        self.assertEqual(mutation_calls, [])

    def test_validation_not_found_and_unknown_routes_use_structured_errors(
        self,
    ) -> None:
        cases = (
            (
                "POST",
                "/api/runs",
                {"topic": "missing fields"},
                self.mutation_headers(),
                400,
                "invalid_request",
            ),
            (
                "POST",
                (
                    f"/api/runs/{self.run.run_id}/candidates/"
                    f"{self.pending.candidate_id}/reject"
                ),
                {},
                self.mutation_headers(),
                400,
                "invalid_request",
            ),
            ("GET", "/api/runs/missing", None, {}, 404, "not_found"),
            ("GET", "/api/jobs/missing", None, {}, 404, "not_found"),
            ("GET", "/api/not-a-route", None, {}, 404, "not_found"),
            ("POST", "/api/not-a-route", {}, self.mutation_headers(), 404, "not_found"),
        )
        for method, path, body, headers, expected_status, code in cases:
            with self.subTest(method=method, path=path):
                status, response_headers, payload = self.request(
                    method,
                    path,
                    body,
                    headers=headers,
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["error"]["code"], code)
                self.assertIsInstance(payload["error"]["message"], str)
                self.assert_json_headers(response_headers)

    def test_unexpected_exception_is_not_leaked(self) -> None:
        secret = "DATABASE_PASSWORD=do-not-leak"

        def explode() -> list[dict[str, object]]:
            raise RuntimeError(secret)

        self.service.list_runs = explode  # type: ignore[method-assign]
        status, _, payload = self.request("GET", "/api/runs")

        self.assertEqual(status, 500)
        self.assertEqual(
            payload,
            {
                "error": {
                    "code": "internal_error",
                    "message": "An internal server error occurred.",
                }
            },
        )
        self.assertNotIn(secret, json.dumps(payload))

    def test_static_routes_serve_allowlisted_utf8_assets_with_security_headers(
        self,
    ) -> None:
        expected = {
            "/": "text/html; charset=utf-8",
            f"/?run={self.run.run_id}": "text/html; charset=utf-8",
            "/static/styles.css": "text/css; charset=utf-8",
            "/static/styles.css?v=workbench": "text/css; charset=utf-8",
            "/static/app.js": "application/javascript; charset=utf-8",
            "/static/app.js?v=workbench": "application/javascript; charset=utf-8",
        }
        for path, content_type in expected.items():
            with self.subTest(path=path):
                status, headers, body = self.request_bytes("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], content_type)
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                self.assertEqual(headers["x-frame-options"], "DENY")
                self.assertEqual(
                    headers["content-security-policy"],
                    (
                        "default-src 'self'; script-src 'self'; style-src 'self'; "
                        "connect-src 'self'; img-src 'self' data:; "
                        "object-src 'none'; base-uri 'none'; "
                        "frame-ancestors 'none'"
                    ),
                )
                self.assertEqual(int(headers["content-length"]), len(body))
                body.decode("utf-8")

    def test_index_injects_safe_json_config(self) -> None:
        status, _, body = self.request_bytes("GET", "/")
        parser = _WorkbenchConfigParser()
        parser.feed(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(parser.config),
            {
                "mutationToken": self.token,
                "defaultCorpusPath": str(self.corpus_path),
                "databasePath": str(self.store.path),
                "artifactRoot": str(self.manager.artifact_root),
                "providers": list(self.manager.provider_options),
            },
        )
        self.assertNotIn("__WORKBENCH_CONFIG__", body.decode("utf-8"))

    def test_index_config_escapes_script_closing_sequences(self) -> None:
        server = create_workbench_server(
            self.service,
            self.manager,
            mutation_token="token</script><script>alert(1)</script>",
            default_corpus_path=Path("</script><img src=x>"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                server.server_address[1],
                timeout=3,
            )
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        parser = _WorkbenchConfigParser()
        parser.feed(body)
        config = json.loads(parser.config)
        self.assertEqual(
            config["mutationToken"],
            "token</script><script>alert(1)</script>",
        )
        self.assertNotIn("</script><script>alert(1)</script>", body)
        self.assertNotIn("</script><img src=x>", body)

    def test_static_allowlist_rejects_unknown_and_traversal_paths(self) -> None:
        paths = (
            "/static/index.html",
            "/static/unknown.css",
            "/static/../app.js",
            "/static/%2e%2e/app.js",
            "/assets/app.js",
            "/api/runs/extra/path",
        )
        for path in paths:
            with self.subTest(path=path):
                status, headers, payload = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"]["code"], "not_found")
                self.assert_json_headers(headers)


class _WorkbenchConfigParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self.config = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        self._capture = tag == "script" and values.get("id") == "workbench-config"

    def handle_data(self, data: str) -> None:
        if self._capture:
            self.config += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._capture = False


class WorkbenchStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.static_root = (
            Path(__file__).parents[1]
            / "src"
            / "literature_review"
            / "workbench"
            / "static"
        )

    def test_index_contains_required_semantic_controls_and_states(self) -> None:
        index = (self.static_root / "index.html").read_text(encoding="utf-8")
        required_fragments = (
            "<h1",
            'id="language-toggle"',
            'id="new-run-button"',
            'id="events-button"',
            'id="cancel-run-button"',
            'id="resume-run-button"',
            'id="close-discovery-button"',
            'id="runs-list"',
            'id="candidate-filters"',
            'id="candidates-body"',
            'id="discovery-empty"',
            'id="candidate-detail"',
            'id="approval-form"',
            'id="new-run-dialog"',
            'id="events-dialog"',
            'id="app-loading"',
            'id="app-empty"',
            'id="app-error"',
            'id="feedback"',
            'id="equivalent-command"',
            'id="workbench-config"',
            'id="provider-options"',
            'id="database-path"',
            'id="artifact-root"',
            'id="runtime-panel"',
            'id="runtime-backend"',
            'id="runtime-model"',
            'id="runtime-executor"',
            'id="runtime-error"',
            'id="discovery-panel"',
            'id="discovery-summary-title"',
            'id="discovery-summary-status"',
            'id="retry-discovery-button"',
            'id="discovery-funnel"',
            'id="discovery-provider-list"',
            'id="discovery-attempts"',
            'id="discovery-recommendations"',
            'id="retry-discovery-dialog"',
            'id="retry-queries"',
            'id="candidate-state-title"',
            'id="candidate-state-message"',
            "__WORKBENCH_CONFIG__",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, index)
        self.assertEqual(index.count("<h1"), 1)
        self.assertNotIn('id="provider-arxiv"', index)
        self.assertNotIn('id="provider-s2"', index)

    def test_client_declares_api_routes_statuses_and_translation_dictionaries(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        required_fragments = (
            "const messages =",
            '"en"',
            '"zh-CN"',
            '"/api/runs"',
            '"/api/jobs/"',
            '"/api/jobs?status=active"',
            '"/api/jobs"',
            '"/events"',
            '"/candidates"',
            '"/approve"',
            '"/defer"',
            '"/reject"',
            '"/resume"',
            '"/cancel"',
            '"/close-discovery"',
            '"/retry-discovery"',
            '"waiting"',
            '"active"',
            '"paused"',
            '"retry_wait"',
            '"failed"',
            '"cancelled"',
            '"completed"',
            "localStorage",
            "selectedRunQueryParam",
            "urlSelectedRunId()",
            "selectedRunStorageKey",
            "storedSelectedRunId()",
            "updateSelectedRunUrl(runId)",
            "storeSelectedRunId(runId)",
            "function runHref(",
            'link.addEventListener("click"',
            "selectRun(run.run_id)",
            "window.history.replaceState",
            "navigator.languages",
            "X-Workbench-Token",
            "runtimeBackend:",
            "runtimeModel:",
            "runtimeExecutor:",
            "runtimeError:",
            "discoveryEmptyTitle:",
            "discoveryEmptyHint:",
            "discoverySummaryTitle:",
            "discoveryIssue_running:",
            "discoveryMessage_running:",
            "discoveryIssue_zero_candidates:",
            "discoveryMessage_zero_candidates:",
            "discoveryMessage_zero_candidates_completed:",
            "continueSeedCorpus:",
            "providerSummary:",
            "providerErrors:",
            "providerErrorLabel_rate_limited:",
            "recommendation_continue_with_seed_corpus:",
            "function renderDiscoverySummary(",
            "function discoverySummary(",
            "function isZeroCandidateDiscoveryGate(",
            "approvalGateOpen",
            "function hasDiscoveryActivity(",
            'byId("discovery-empty").hidden',
            'byId("close-discovery-button").textContent',
            "startJobs: new Map()",
            "manualSelectionVersion: 0",
            'job.kind === "start"',
            "function refreshStartJobRuns(",
            "function recoverActiveJobs(",
            "await recoverActiveJobs()",
            'job.status === "interrupted"',
            't("jobInterrupted")',
            "function renderProviderOptions(",
            "config.providers",
            "input.name = name",
            "function openRetryDiscoveryDialog(",
            "async function retryDiscovery(",
            "function queryLines(",
            "state.manualSelectionVersion += 1",
            "&& !state.selectedRunId",
            "fallbackToFirst = false",
            "(!selectedExists && fallbackToFirst)",
            "loadRuns({ preserveSelection: true, fallbackToFirst: true });",
            "await loadRuns({ preserveSelection: true, force: true })",
            "backend_deterministic:",
            "backend_api:",
            "model_deterministic:",
            "model_multiple_models:",
            "executor_model_agent_loop:",
            "executor_deterministic_agent_loop:",
            "retryable_api_failure:",
            "permanent_api_failure:",
            "pagehide",
            "setTimeout",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_client_guards_stale_run_and_candidate_responses(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        required_fragments = (
            "runGeneration: 0",
            "candidateGeneration: 0",
            "function beginRunSelection(",
            "function isCurrentRunRequest(",
            "function isCurrentCandidateRequest(",
            "function refreshRunDetail(",
            "beginRunSelection(runId)",
            "isCurrentRunRequest(runId, generation)",
            "isCurrentCandidateRequest(runId, filter, runGeneration, candidateGeneration)",
            "await refreshRunDetail(runId)",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)
        self.assertNotIn("loadingDetail: false", script)

    def test_client_calls_candidate_endpoint_for_each_filter_mode(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")

        self.assertIn("function candidateRequestPath(runId, filter)", script)
        self.assertIn('filter === "pending" || filter === "approved"', script)
        self.assertIn("encodeURIComponent(filter)", script)
        self.assertIn("api(candidateRequestPath(runId, filter))", script)
        self.assertIn('filter === "recommended"', script)
        self.assertIn('candidate.recommendation === "include"', script)

    def test_client_resets_form_and_requires_nonempty_trimmed_tags(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        required_fragments = (
            "function resetCandidateForm(",
            'byId("candidate-category").value = ""',
            'byId("candidate-contribution").value = ""',
            'byId("candidate-tags").value = ""',
            'byId("candidate-reason").value = ""',
            'showFeedback("")',
            "tagsRequired:",
            "if (tags.length === 0)",
            'showFeedback(t("tagsRequired"), true)',
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_background_form_refresh_does_not_clear_job_feedback(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        reset_start = script.index("function resetCandidateForm(")
        reset_end = script.index("\n  function beginRunSelection(", reset_start)
        reset_body = script[reset_start:reset_end]

        self.assertNotIn("showFeedback", reset_body)
        self.assertNotIn("clearFeedback", reset_body)

    def test_pending_state_marks_run_links_disabled_after_mutation(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        update_start = script.index("function updateActions(")
        update_end = script.index("\n  async function selectRun(", update_start)
        update_body = script[update_start:update_end]

        self.assertIn('document.querySelectorAll(".run-button")', update_body)
        self.assertIn('link.setAttribute("aria-disabled", String(disabled))', update_body)
        self.assertIn('link.classList.toggle("disabled", disabled)', update_body)

    def test_run_links_preserve_spa_job_tracking_for_plain_navigation(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        render_start = script.index("function renderRuns()")
        render_end = script.index("\n  function runStatusLabel(", render_start)
        render_body = script[render_start:render_end]

        self.assertIn('link.addEventListener("click"', render_body)
        self.assertIn('link.getAttribute("aria-disabled")', render_body)
        self.assertIn("event.metaKey", render_body)
        self.assertIn("event.ctrlKey", render_body)
        self.assertIn("event.preventDefault()", render_body)
        self.assertIn("selectRun(run.run_id)", render_body)

    def test_candidate_decisions_require_visible_approval_gate(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        detail_start = script.index("function renderCandidateDetail()")
        detail_end = script.index("\n  function renderIdentifiers(", detail_start)
        detail_body = script[detail_start:detail_end]

        self.assertIn('run.status === "waiting"', detail_body)
        self.assertIn(
            'run.current_stage === "awaiting_corpus_approval"',
            detail_body,
        )
        self.assertIn("|| !approvalGateOpen", detail_body)

    def test_index_contains_accessible_run_deletion_controls(self) -> None:
        index = (self.static_root / "index.html").read_text(encoding="utf-8")
        required_fragments = (
            'id="delete-run-button"',
            'id="delete-run-dialog"',
            'aria-labelledby="delete-run-heading"',
            'aria-describedby="delete-run-description"',
            'id="delete-run-topic"',
            'id="delete-run-id"',
            'id="delete-run-status"',
            'id="delete-run-description"',
            'id="delete-run-unaffected"',
            'id="delete-run-close-button"',
            'id="confirm-delete-run-button"',
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, index)
        self.assertLess(
            index.index('id="cancel-run-button"'),
            index.index('id="delete-run-button"'),
        )

    def test_client_deletion_flow_is_terminal_only_bodyless_and_focus_safe(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        update_start = script.index("function updateActions(")
        update_end = script.index("\n  async function selectRun(", update_start)
        update_body = script[update_start:update_end]
        open_start = script.index("function openDeleteRunDialog(")
        open_end = script.index("\n  function dismissDeleteRunDialog(", open_start)
        open_body = script[open_start:open_end]
        delete_start = script.index("async function deleteRun(")
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]
        required_global_fragments = (
            'const deletableRunStatuses = new Set(["cancelled", "completed", "failed"])',
            "function openDeleteRunDialog(",
            "function dismissDeleteRunDialog(",
            "async function deleteRun(",
        )
        for fragment in required_global_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)
        self.assertIn('byId("delete-run-button").disabled =', update_body)
        self.assertIn("!deletableRunStatuses.has(run && run.status)", update_body)
        self.assertIn('byId("delete-run-close-button").focus()', open_body)
        self.assertIn("encodeURIComponent(runId)", delete_body)
        self.assertIn('{ method: "DELETE" }', delete_body)
        self.assertIn('byId("confirm-delete-run-button").disabled = true', delete_body)
        self.assertIn("showCommand(payload)", delete_body)
        self.assertIn("payload.cleanup_pending", delete_body)
        self.assertIn(
            'await loadRuns({ preserveSelection: false, force: true })',
            delete_body,
        )
        self.assertNotIn('{ method: "DELETE", body:', script)

    def test_client_deletion_copy_covers_scope_warnings_and_conflicts_in_both_locales(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        required_fragments = (
            "Delete run",
            "Delete permanently",
            "SQLite history and run artifacts will be removed.",
            "The seed corpus and shared provider cache are unaffected.",
            "Run deleted permanently.",
            "Run deleted, but artifact cleanup is still pending.",
            "删除运行",
            "永久删除",
            "SQLite 历史记录和运行产物将被删除。",
            "种子语料库和共享检索平台缓存不受影响。",
            "运行已永久删除。",
            "运行已删除，但产物清理仍在等待完成。",
            "run_not_deletable:",
            "run_deletion_conflict:",
            "run_busy:",
            "run_deletion_busy:",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_run_deletion_does_not_clear_background_job_feedback(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        delete_start = script.index("async function deleteRun(")
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]

        self.assertNotIn('showFeedback("")', delete_body)
        self.assertNotIn("withPending(", delete_body)

    def test_persistent_feedback_suppresses_chatter_but_yields_to_background_errors(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        feedback_start = script.index("function showFeedback(")
        feedback_end = script.index("\n  function errorMessage(", feedback_start)
        feedback_body = script[feedback_start:feedback_end]

        chatter_guard = (
            "if (options.background && state.stableFeedback && !isError) return;"
        )
        self.assertIn(chatter_guard, feedback_body)
        self.assertIn("if (!options.background || isError)", feedback_body)
        self.assertLess(
            feedback_body.index(chatter_guard),
            feedback_body.index("state.stableFeedback ="),
        )

    def test_post_delete_reload_is_forced_queued_and_stale_safe(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        required_fragments = (
            "runReloadPromise: null",
            "queuedRunReload: null",
            "runReloadGeneration: 0",
            "async function performRunLoad(",
            "if (state.runReloadPromise)",
            "if (force)",
            "state.queuedRunReload =",
            "return state.runReloadPromise",
            "generation !== state.runReloadGeneration",
            "while (request && !state.stopped)",
            'await loadRuns({ preserveSelection: false, force: true })',
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_normal_delete_success_is_persistent_and_keeps_equivalent_cli(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        delete_start = script.index("async function deleteRun(")
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]

        self.assertIn("showCommand(payload)", delete_body)
        self.assertIn('payload.cleanup_pending ? "deleteCleanupPending" : "runDeleted"', delete_body)
        self.assertIn("persistent: true", delete_body)

    def test_delete_dialog_focus_is_deferred_until_actions_are_enabled(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        self.assertIn("function focusPostDeleteTarget(", script)
        self.assertIn("function isDeleteConflict(", script)
        dismiss_start = script.index("function dismissDeleteRunDialog(")
        dismiss_end = script.index("\n  function focusPostDeleteTarget(", dismiss_start)
        dismiss_body = script[dismiss_start:dismiss_end]
        focus_start = dismiss_end + 3
        focus_end = script.index("\n  function isDeleteConflict(", focus_start)
        focus_body = script[focus_start:focus_end]
        delete_start = script.index("async function deleteRun(")
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]

        self.assertIn("restoreFocus = true", dismiss_body)
        self.assertIn("if (restoreFocus)", dismiss_body)
        self.assertIn('byId("delete-run-button").focus()', dismiss_body)
        self.assertIn('byId("delete-run-button")', focus_body)
        self.assertIn(
            'document.querySelector(\'.run-button.selected:not([aria-disabled="true"])\')',
            focus_body,
        )
        self.assertIn('byId("empty-new-run-button")', focus_body)
        self.assertIn('byId("new-run-button")', focus_body)
        self.assertIn("dismissDeleteRunDialog({ restoreFocus: false })", delete_body)
        final_start = delete_body.index("finally")
        self.assertLess(
            delete_body.index("state.deletingRun = false", final_start),
            delete_body.index("updateActions()", final_start),
        )
        self.assertLess(
            delete_body.index("updateActions()", final_start),
            delete_body.index("focusPostDeleteTarget()", final_start),
        )

    def test_delete_conflicts_dismiss_refresh_then_focus_after_finalization(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        self.assertIn("function isDeleteConflict(", script)
        conflict_start = script.index("function isDeleteConflict(")
        conflict_end = script.index("\n  async function deleteRun(", conflict_start)
        conflict_body = script[conflict_start:conflict_end]
        delete_start = conflict_end + 3
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]
        catch_start = delete_body.index("catch (error)")
        finally_start = delete_body.index("finally", catch_start)
        catch_body = delete_body[catch_start:finally_start]

        self.assertIn("error instanceof APIError", conflict_body)
        self.assertIn('"run_not_deletable"', conflict_body)
        self.assertIn('"run_deletion_conflict"', conflict_body)
        self.assertIn('"run_busy"', conflict_body)
        self.assertIn('"run_deletion_busy"', conflict_body)
        self.assertIn('"not_found"', conflict_body)
        self.assertIn("if (isDeleteConflict(error))", catch_body)
        self.assertIn("dismissDeleteRunDialog({ restoreFocus: false })", catch_body)
        self.assertIn(
            "await loadRuns({ preserveSelection: true, force: true })",
            catch_body,
        )
        self.assertLess(
            catch_body.index("await loadRuns("),
            catch_body.index("showFeedback(errorMessage(error), true)"),
        )
        self.assertNotIn('byId("delete-run-button").focus()', catch_body)

    def test_delete_not_found_reloads_and_preserves_selection_only_if_present(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        load_start = script.index("async function performRunLoad(")
        load_end = script.index("\n  async function loadRuns(", load_start)
        load_body = script[load_start:load_end]
        conflict_start = script.index("function isDeleteConflict(")
        conflict_end = script.index("\n  async function deleteRun(", conflict_start)
        conflict_body = script[conflict_start:conflict_end]
        delete_start = conflict_end + 3
        delete_end = script.index("\n  function scheduleJobPoll(", delete_start)
        delete_body = script[delete_start:delete_end]
        catch_start = delete_body.index("catch (error)")
        finally_start = delete_body.index("finally", catch_start)
        catch_body = delete_body[catch_start:finally_start]

        self.assertIn('"not_found"', conflict_body)
        self.assertIn(
            "const selectedExists = state.runs.some(",
            load_body,
        )
        self.assertIn(
            "if (!preserveSelection || (!selectedExists && fallbackToFirst))",
            load_body,
        )
        self.assertIn(
            "else beginRunSelection(null)",
            load_body,
        )
        self.assertIn(
            "await loadRuns({ preserveSelection: true, force: true })",
            catch_body,
        )
        self.assertLess(
            catch_body.index("await loadRuns("),
            catch_body.index("showFeedback(errorMessage(error), true)"),
        )
        self.assertIn("focusAfterFinalization = true", catch_body)

    def test_initial_load_selects_a_run_without_changing_refresh_behavior(
        self,
    ) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        initialize_start = script.index("function initialize()")
        initialize_end = script.index("\n  initialize();", initialize_start)
        initialize_body = script[initialize_start:initialize_end]
        refresh_start = script.index("async function refreshStartJobRuns(")
        refresh_end = script.index("\n  async function withPending(", refresh_start)
        refresh_body = script[refresh_start:refresh_end]

        self.assertIn(
            "loadRuns({ preserveSelection: true, fallbackToFirst: true });",
            initialize_body,
        )
        self.assertIn(
            "await loadRuns({ preserveSelection: true, force: true });",
            refresh_body,
        )
        self.assertNotIn("fallbackToFirst: true", refresh_body)

    def test_styles_define_approved_responsive_layout(self) -> None:
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        required_fragments = (
            "#176b54",
            "grid-template-columns: 190px minmax(0, 1fr) 330px",
            "@media (max-width: 1100px)",
            "@media (max-width: 720px)",
            "@media (max-width: 480px)",
            ".runtime-strip",
            "grid-template-columns: repeat(4, minmax(0, 1fr))",
            ".runtime-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }",
            ".discovery-provider-list { grid-template-columns: 1fr; }",
            "grid-template-columns: repeat(3, minmax(0, 1fr))",
            ".candidate-row",
            ":focus-visible",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, styles)
        self.assertNotIn("gradient(", styles)

    def test_runs_list_scrolls_on_larger_viewports_and_flows_on_mobile(
        self,
    ) -> None:
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        desktop_rule = (
            ".runs-list {\n"
            "  max-height: min(50vh, 520px);\n"
            "  overflow-y: auto;\n"
            "  scrollbar-gutter: stable;\n"
            "  overscroll-behavior: contain;\n"
            "}"
        )
        mobile_rule = (
            ".runs-list {\n"
            "    display: grid;\n"
            "    grid-template-columns: repeat(3, minmax(0, 1fr));\n"
            "    gap: 6px;\n"
            "    max-height: none;\n"
            "    overflow: visible;\n"
            "    scrollbar-gutter: auto;\n"
            "    overscroll-behavior: auto;\n"
            "  }"
        )

        self.assertIn(desktop_rule, styles)
        mobile_start = styles.index("@media (max-width: 720px)")
        mobile_end = styles.index("@media (max-width: 480px)", mobile_start)
        self.assertIn(mobile_rule, styles[mobile_start:mobile_end])


if __name__ == "__main__":
    unittest.main()
