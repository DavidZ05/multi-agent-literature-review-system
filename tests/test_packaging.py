from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_github_actions_ci_runs_unit_tests(self) -> None:
        workflow = ROOT / ".github" / "workflows" / "ci.yml"

        text = workflow.read_text(encoding="utf-8")

        self.assertIn("os: [ubuntu-latest, macos-latest]", text)
        self.assertIn("python-version: ['3.11', '3.12']", text)
        self.assertIn("python -m pip install -e .", text)
        self.assertIn("python -m unittest discover -s tests -v", text)
        self.assertIn("literature-review --help", text)
        self.assertIn("python -m compileall -q src tests", text)
        self.assertIn("python -m pip wheel . --no-deps --wheel-dir dist", text)
        self.assertIn("literature-review-workbench --help", text)
        self.assertIn("literature-review plugins", text)
        self.assertIn("doctor", text)

    def test_public_project_files_are_ready_for_distribution(self) -> None:
        required_files = {
            "LICENSE": "MIT License",
            "CHANGELOG.md": "0.7.1",
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
        self.assertIn("pdfplumber>=0.11,<1", project["dependencies"])
        self.assertEqual(
            project["scripts"]["literature-review"],
            "src.literature_review.cli:main",
        )
        self.assertEqual(
            project["scripts"]["literature-review-workbench"],
            "src.literature_review.cli:workbench_main",
        )

    def test_distribution_includes_workbench_static_assets(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())

        package_data = metadata["tool"]["setuptools"]["package-data"]
        self.assertIn("workbench/static/*.html", package_data["src.literature_review"])
        self.assertIn("workbench/static/*.css", package_data["src.literature_review"])
        self.assertIn("workbench/static/*.js", package_data["src.literature_review"])
        self.assertIn("resources/*.json", package_data["src.literature_review"])
        self.assertIn("prompts/*.txt", package_data["src.literature_review"])

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

    def test_readme_is_public_user_first(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        required_sections = [
            "## Quick Start",
            "## Workbench",
            "## Deterministic and API Modes",
            "## Automatic Literature Discovery",
            "## Plugins",
            "## Troubleshooting",
            "## Course Project Archive",
        ]
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, readme)

        self.assertLess(readme.index("## Quick Start"), readme.index("## Workbench"))
        self.assertLess(
            readme.index("## Workbench"),
            readme.index("## Deterministic and API Modes"),
        )
        self.assertIn("macOS or Linux", readme)
        self.assertIn("python3 -m pip install -e .", readme)
        self.assertIn("literature-review --help", readme)
        self.assertIn("literature-review doctor", readme)
        self.assertIn("literature-review-workbench", readme)
        self.assertIn("literature-review plugins", readme)
        self.assertIn("docs/plugin_development.md", readme)
        self.assertIn("AGENT_BACKEND=deterministic", readme)
        self.assertIn("AGENT_BACKEND=api", readme)
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY", readme)
        self.assertIn("certifi", readme)
        self.assertIn("SSL_CERT_FILE", readme)
        self.assertIn("docs/course-project/FINAL_SUBMISSION.md", readme)
        self.assertNotIn("Final Assignment Deliverables", readme)

    def test_course_project_material_is_archived(self) -> None:
        archive = ROOT / "docs" / "course-project"
        expected = [
            archive / "FINAL_SUBMISSION.md",
            archive / "design_document.md",
            archive / "seed_corpus_review.md",
        ]
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
        self.assertFalse((ROOT / "FINAL_SUBMISSION.md").exists())
        self.assertFalse((ROOT / "docs" / "design_document.md").exists())
        self.assertFalse((ROOT / "docs" / "seed_corpus_review.md").exists())

    def test_plugin_development_guide_documents_entry_point_contracts(self) -> None:
        guide = (ROOT / "docs" / "plugin_development.md").read_text(encoding="utf-8")

        self.assertIn('literature_review.providers', guide)
        self.assertIn('literature_review.agents', guide)
        self.assertIn('ProviderContext', guide)
        self.assertIn('final_verification', guide)
        self.assertIn('trusted code', guide)


if __name__ == "__main__":
    unittest.main()
