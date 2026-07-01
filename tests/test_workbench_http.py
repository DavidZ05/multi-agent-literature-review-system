from concurrent.futures import Future
import http.client
import json
from pathlib import Path
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
            return response.status, response_headers, json.loads(raw)
        finally:
            connection.close()

    def mutation_headers(self, **extra: str) -> dict[str, str]:
        return {"X-Workbench-Token": self.token, **extra}

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

    def test_static_and_non_api_routes_do_not_capture_unknown_api_routes(self) -> None:
        for path in ("/", "/assets/app.js", "/api/runs/extra/path"):
            with self.subTest(path=path):
                status, _, payload = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
