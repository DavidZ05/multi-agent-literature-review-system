from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from src.literature_review.models import SearchQuery
from src.literature_review.providers.http import HttpResponse
from src.literature_review.providers.semantic_scholar import (
    SemanticScholarProvider,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "providers" / "semantic_scholar_memory.json"
).read_bytes()


class MemoryCache:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value, ttl_seconds):
        self.values[key] = value


class FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, dict(headers)))
        return HttpResponse(200, FIXTURE, {"content-type": "application/json"})


class SemanticScholarProviderTests(unittest.TestCase):
    def test_maps_fixture_and_handles_nullable_fields(self) -> None:
        provider = SemanticScholarProvider(FakeTransport(), MemoryCache())
        result = provider.search(
            SearchQuery(
                "q1",
                "LLM agent memory",
                "semantic_scholar",
                10,
                None,
                None,
            )
        )

        first, second = result.papers
        self.assertEqual(first.semantic_scholar_id, "s2-generative-agents")
        self.assertEqual(first.doi, "10.1145/3586183.3606763")
        self.assertEqual(first.arxiv_id, "2304.03442")
        self.assertEqual(
            first.open_access_pdf_url,
            "https://arxiv.org/pdf/2304.03442",
        )
        self.assertIsNone(second.abstract)
        self.assertIsNone(second.venue)
        self.assertIsNone(second.open_access_pdf_url)
        self.assertEqual(second.authors, ("Zeyu Zhang",))
        self.assertEqual(second.arxiv_id, "2404.13501")

    def test_builds_request_and_keeps_api_key_in_header_only(self) -> None:
        transport = FakeTransport()
        provider = SemanticScholarProvider(
            transport,
            MemoryCache(),
            api_key="secret-key",
        )

        provider.search(
            SearchQuery(
                "q1",
                "LLM agent memory",
                "semantic_scholar",
                500,
                None,
                None,
            )
        )

        url, headers = transport.calls[0]
        parsed = parse_qs(urlparse(url).query)
        self.assertEqual(parsed["query"], ["LLM agent memory"])
        self.assertEqual(parsed["limit"], ["100"])
        self.assertIn("title,abstract,year,venue,authors", parsed["fields"][0])
        self.assertEqual(headers["x-api-key"], "secret-key")
        self.assertNotIn("secret-key", url)

    def test_identical_search_uses_cache(self) -> None:
        transport = FakeTransport()
        provider = SemanticScholarProvider(transport, MemoryCache())
        query = SearchQuery("q1", "memory", "semantic_scholar", 5, None, None)
        provider.search(query)
        provider.search(query)
        self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
