from concurrent.futures import Future
import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest

from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    ScreeningRecommendation,
    WorkflowStage,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench import (
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
            (f"/api/jobs/{accepted['job_id']}", self.manager.get_job(accepted["job_id"])),
        )

        self.assertEqual(accepted_status, 202)
        for path, expected in cases:
            with self.subTest(path=path):
                status, headers, payload = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(payload, expected)
                self.assert_json_headers(headers)

    def test_candidate_status_filter_rejects_invalid_value(self) -> None:
        status, _, payload = self.request(
            "GET",
            f"/api/runs/{self.run.run_id}/candidates?status=unknown",
        )

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

    def test_run_and_candidate_mutation_route_families_return_service_payloads(
        self,
    ) -> None:
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

    def test_close_discovery_returns_pending_conflict_then_service_payload(self) -> None:
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
            "/static/styles.css": "text/css; charset=utf-8",
            "/static/app.js": "application/javascript; charset=utf-8",
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
                        "connect-src 'self'; object-src 'none'; base-uri 'none'; "
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
            'id="database-path"',
            'id="artifact-root"',
            'id="candidate-state-title"',
            'id="candidate-state-message"',
            "__WORKBENCH_CONFIG__",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, index)
        self.assertEqual(index.count("<h1"), 1)

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
            '"/events"',
            '"/candidates"',
            '"/approve"',
            '"/defer"',
            '"/reject"',
            '"/resume"',
            '"/cancel"',
            '"/close-discovery"',
            '"waiting"',
            '"active"',
            '"paused"',
            '"retry_wait"',
            '"failed"',
            '"cancelled"',
            '"completed"',
            "localStorage",
            "navigator.languages",
            "X-Workbench-Token",
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

    def test_pending_state_reenables_run_buttons_after_mutation(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        update_start = script.index("function updateActions(")
        update_end = script.index("\n  async function selectRun(", update_start)
        update_body = script[update_start:update_end]

        self.assertIn('document.querySelectorAll(".run-button")', update_body)
        self.assertIn("button.disabled = state.pending", update_body)

    def test_styles_define_approved_responsive_layout(self) -> None:
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        required_fragments = (
            "#176b54",
            "grid-template-columns: 190px minmax(0, 1fr) 330px",
            "@media (max-width: 1100px)",
            "@media (max-width: 720px)",
            "@media (max-width: 480px)",
            "grid-template-columns: repeat(4, minmax(0, 1fr))",
            "grid-template-columns: repeat(3, minmax(0, 1fr))",
            ".candidate-row",
            ":focus-visible",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, styles)
        self.assertNotIn("gradient(", styles)


if __name__ == "__main__":
    unittest.main()
