import os
import unittest

from src.literature_review.models import SearchQuery
from src.literature_review.providers import (
    ArxivProvider,
    NullResponseCache,
    SemanticScholarProvider,
    UrllibHttpTransport,
)


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_PROVIDER_TESTS") == "1",
    "set RUN_LIVE_PROVIDER_TESTS=1 to call live literature providers",
)
class LiveProviderSmokeTests(unittest.TestCase):
    def test_arxiv_returns_at_most_two_results(self) -> None:
        provider = ArxivProvider(UrllibHttpTransport(), NullResponseCache())
        result = provider.search(
            SearchQuery("live_arxiv", "LLM agent memory", "arxiv", 2, None, None)
        )
        self.assertLessEqual(len(result.papers), 2)

    def test_semantic_scholar_returns_at_most_two_results(self) -> None:
        provider = SemanticScholarProvider(
            UrllibHttpTransport(),
            NullResponseCache(),
            api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
        )
        result = provider.search(
            SearchQuery(
                "live_s2",
                "LLM agent memory",
                "semantic_scholar",
                2,
                None,
                None,
            )
        )
        self.assertLessEqual(len(result.papers), 2)


if __name__ == "__main__":
    unittest.main()
