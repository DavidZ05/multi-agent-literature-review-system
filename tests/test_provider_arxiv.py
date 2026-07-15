from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from src.literature_review.models import SearchQuery
from src.literature_review.providers.arxiv import ArxivProvider
from src.literature_review.providers.http import HttpResponse


FIXTURE = (
    Path(__file__).parent / "fixtures" / "providers" / "arxiv_memory.xml"
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
        self.calls.append((url, headers))
        return HttpResponse(200, FIXTURE, {"content-type": "application/atom+xml"})


class ArxivProviderTests(unittest.TestCase):
    def test_parses_atom_fixture_and_normalizes_metadata(self) -> None:
        provider = ArxivProvider(FakeTransport(), MemoryCache())
        result = provider.search(
            SearchQuery("q1", "LLM agent memory", "arxiv", 10, None, None)
        )

        first = result.papers[0]
        self.assertEqual(first.arxiv_id, "2304.03442")
        self.assertEqual(first.year, 2023)
        self.assertEqual(first.authors[0], "Joon Sung Park")
        self.assertEqual(first.doi, "10.1145/3586183.3606763")
        self.assertEqual(
            first.open_access_pdf_url,
            "https://arxiv.org/pdf/2304.03442v2",
        )
        self.assertNotIn("\n", first.title)

    def test_builds_encoded_search_request_and_reuses_cache(self) -> None:
        transport = FakeTransport()
        cache = MemoryCache()
        provider = ArxivProvider(transport, cache)
        query = SearchQuery("q1", 'LLM agent "memory"', "arxiv", 500, None, None)

        provider.search(query)
        provider.search(query)

        self.assertEqual(len(transport.calls), 1)
        parsed = parse_qs(urlparse(transport.calls[0][0]).query)
        self.assertEqual(
            parsed["search_query"],
            ["all:llm AND all:agent AND all:memory"],
        )
        self.assertEqual(parsed["start"], ["0"])
        self.assertEqual(parsed["max_results"], ["100"])
        self.assertEqual(parsed["sortBy"], ["relevance"])
        self.assertEqual(parsed["sortOrder"], ["descending"])

    def test_search_expression_preserves_unicode_terms(self) -> None:
        self.assertEqual(
            ArxivProvider._search_expression("多智能体 记忆 评估"),
            "all:多智能体 AND all:记忆 AND all:评估",
        )

    def test_throttles_consecutive_uncached_requests(self) -> None:
        now = [10.0]
        delays = []
        provider = ArxivProvider(
            FakeTransport(),
            MemoryCache(),
            clock=lambda: now[0],
            sleeper=delays.append,
        )
        provider.search(SearchQuery("q1", "memory", "arxiv", 1, None, None))
        now[0] = 11.0
        provider.search(SearchQuery("q2", "episodic memory", "arxiv", 1, None, None))

        self.assertEqual(delays, [2.0])


if __name__ == "__main__":
    unittest.main()
