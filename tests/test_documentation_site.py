from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"


class DocumentationSiteTests(unittest.TestCase):
    def test_site_configuration_has_public_url_and_required_navigation(self) -> None:
        config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        self.assertIn(
            "site_url: https://davidz05.github.io/multi-agent-literature-review-system/",
            config,
        )
        self.assertIn("docs_dir: site", config)
        for page in (
            "index.md",
            "getting-started.md",
            "workflow.md",
            "reliability.md",
            "configuration.md",
            "plugins.md",
            "security.md",
            "roadmap.md",
            "zh/quick-start.md",
        ):
            self.assertIn(page, config)
            self.assertTrue((SITE_ROOT / page).is_file(), page)

    def test_pages_workflow_builds_strictly_and_uses_official_actions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("mkdocs build --strict", workflow)
        self.assertRegex(workflow, r"actions/configure-pages@v\d+")
        self.assertRegex(workflow, r"actions/upload-pages-artifact@v\d+")
        self.assertRegex(workflow, r"actions/deploy-pages@v\d+")
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)

    def test_public_site_contains_no_local_paths_or_secret_values(self) -> None:
        forbidden = (
            re.compile(r"/Users/"),
            re.compile(r"/home/[^/\s]+/"),
            re.compile(r"(?i)(?:api[_-]?key|token)\s*=\s*['\"]?[A-Za-z0-9_-]{12,}"),
        )

        for path in SITE_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".html", ".css", ".js"}:
                continue
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertIsNone(pattern.search(content), f"{pattern.pattern} in {path}")

    def test_homepage_uses_a_real_workbench_capture(self) -> None:
        image = SITE_ROOT / "assets" / "images" / "workbench-overview.png"

        self.assertTrue(image.is_file())
        self.assertGreater(image.stat().st_size, 50_000)

    def test_release_version_is_consistent(self) -> None:
        expected = "0.8.1"
        sources = {
            "pyproject.toml": ROOT / "pyproject.toml",
            "package.json": ROOT / "package.json",
            "version.py": ROOT / "src" / "literature_review" / "version.py",
        }

        for label, path in sources.items():
            self.assertIn(expected, path.read_text(encoding="utf-8"), label)
        self.assertIn("## 0.8.1", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
