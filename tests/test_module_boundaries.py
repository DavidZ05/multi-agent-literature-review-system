import json
import tempfile
import unittest
from pathlib import Path


class ModuleBoundaryTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        from src import literature_review

        self.assertEqual(literature_review.__version__, "0.1.0")


class CorpusModuleTests(unittest.TestCase):
    def test_load_papers_rejects_duplicate_citation_key(self) -> None:
        from src.literature_review.corpus import load_papers

        paper = {
            "citation_key": "smith2024",
            "title": "A Study",
            "authors": ["Jane Smith"],
            "year": 2024,
            "venue": "Test Venue",
            "url": "https://example.com/paper",
            "category": "memory",
            "contribution": "Analysis",
            "evidence": "Evidence",
            "tags": ["one"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            corpus = Path(tmpdir) / "papers.json"
            corpus.write_text(json.dumps([paper, dict(paper)]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate citation_key"):
                load_papers(corpus)


if __name__ == "__main__":
    unittest.main()
