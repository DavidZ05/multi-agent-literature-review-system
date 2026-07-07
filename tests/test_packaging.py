from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_public_project_files_are_ready_for_distribution(self) -> None:
        required_files = {
            "LICENSE": "MIT License",
            "CHANGELOG.md": "0.3.0",
            "CONTRIBUTING.md": "Contributing",
            "SECURITY.md": "Security",
        }

        for filename, expected_text in required_files.items():
            with self.subTest(filename=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn(expected_text, text)
                self.assertNotIn("TODO", text)
                self.assertNotIn("TBD", text)

    def test_pyproject_declares_supported_install_and_console_command(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

        project = metadata["project"]
        self.assertEqual(project["name"], "multi-agent-literature-review-system")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertIn("certifi>=2024.2.2", project["dependencies"])
        self.assertEqual(
            project["scripts"]["literature-review"],
            "src.literature_review.cli:main",
        )

    def test_distribution_includes_workbench_static_assets(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

        package_data = metadata["tool"]["setuptools"]["package-data"]
        self.assertIn("workbench/static/*.html", package_data["src.literature_review"])
        self.assertIn("workbench/static/*.css", package_data["src.literature_review"])
        self.assertIn("workbench/static/*.js", package_data["src.literature_review"])
        self.assertIn("resources/*.json", package_data["src.literature_review"])

    def test_default_corpus_is_available_as_a_package_resource(self) -> None:
        packaged = (
            ROOT
            / "src"
            / "literature_review"
            / "resources"
            / "papers.json"
        )
        self.assertTrue(packaged.is_file())
        self.assertEqual(
            packaged.read_bytes(),
            (ROOT / "data" / "papers.json").read_bytes(),
        )

    def test_package_has_module_entrypoint(self) -> None:
        entrypoint = ROOT / "src" / "literature_review" / "__main__.py"
        self.assertTrue(entrypoint.is_file())
        self.assertIn("raise SystemExit(main())", entrypoint.read_text())


if __name__ == "__main__":
    unittest.main()
