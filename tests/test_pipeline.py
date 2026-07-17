import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_review_pipeline import (
    AgentRuntimeConfig,
    EvaluationReflectionAgent,
    FinalVerificationReviewer,
    Orchestrator,
    ReviewerAgent,
    SearchAgent,
    WriterAgent,
    load_papers,
)
from src.literature_review.config import AgentConfigurationError


def write_sample_corpus(path: Path) -> None:
    papers = [
        {
            "citation_key": "packer2023memgpt",
            "title": "MemGPT: Towards LLMs as Operating Systems",
            "authors": ["Charles Packer", "Sarah Wooders"],
            "year": 2023,
            "venue": "arXiv",
            "url": "https://arxiv.org/abs/2310.08560",
            "category": "hierarchical memory",
            "contribution": "Introduces virtual context management for long-running LLM agents.",
            "evidence": "verified",
            "tags": ["hierarchical", "long-term memory"],
        },
        {
            "citation_key": "shinn2023reflexion",
            "title": "Reflexion: Language Agents with Verbal Reinforcement Learning",
            "authors": ["Noah Shinn", "Federico Cassano"],
            "year": 2023,
            "venue": "NeurIPS",
            "url": "https://arxiv.org/abs/2303.11366",
            "category": "reflective memory",
            "contribution": "Stores verbal reflections in episodic memory for later trials.",
            "evidence": "verified",
            "tags": ["reflection", "episodic memory"],
        },
    ]
    path.write_text(json.dumps(papers), encoding="utf-8")


class PipelineTests(unittest.TestCase):
    def test_load_papers_requires_unique_citation_keys_and_urls(self) -> None:
        with TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "papers.json"
            write_sample_corpus(corpus)

            papers = load_papers(corpus)

            self.assertEqual(
                [paper["citation_key"] for paper in papers],
                ["packer2023memgpt", "shinn2023reflexion"],
            )
            self.assertTrue(
                all(paper["url"].startswith("https://") for paper in papers)
            )

    def test_orchestrator_generates_survey_and_review_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "papers.json"
            output_dir = root / "outputs"
            write_sample_corpus(corpus)

            result = Orchestrator(corpus_path=corpus, output_dir=output_dir).run()

            survey = (output_dir / "survey.md").read_text(encoding="utf-8")
            review = json.loads(
                (output_dir / "review_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "accepted")
            self.assertIn("Memory-Augmented LLM Agents", survey)
            self.assertIn("[packer2023memgpt]", survey)
            self.assertIn("[shinn2023reflexion]", survey)
            self.assertIn("## 2. Methodology", survey)
            self.assertIn("Mechanism Comparison", survey)
            self.assertIn("Human-in-the-loop checkpoints", survey)
            self.assertEqual(review["unknown_citations"], [])
            self.assertIn("expert_panel", review)
            self.assertIn("revision_plan", review)

            expected_artifacts = [
                output_dir / "intermediate" / "citation_audit.json",
                output_dir / "intermediate" / "domain_review.json",
                output_dir / "intermediate" / "structure_review.json",
                output_dir / "intermediate" / "revision_plan.json",
                output_dir / "final_verification.json",
                output_dir / "evaluation_report.json",
                output_dir / "reflection_log.md",
            ]
            for artifact in expected_artifacts:
                self.assertTrue(artifact.exists(), f"{artifact} was not generated")

    def test_orchestrator_preserves_optional_run_trace(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "papers.json"
            corpus.write_text(
                json.dumps(
                    [
                        {
                            "citation_key": "seed2026",
                            "title": "Seed",
                            "authors": ["A. Author"],
                            "year": 2026,
                            "venue": "Test Venue",
                            "url": "https://example.com/seed",
                            "category": "memory mechanism",
                            "contribution": "A seed memory mechanism.",
                            "evidence": "Metadata checked.",
                            "tags": ["memory"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            run_id = "run_0123456789abcdef0123456789abcdef"

            result = Orchestrator(
                corpus_path=corpus,
                output_dir=root / "outputs",
                run_id=run_id,
            ).run()

            self.assertEqual(result["run_id"], run_id)

    def test_writer_discusses_new_approved_category_in_body(self) -> None:
        papers = [
            {
                "citation_key": "new2026social",
                "title": "Social Memory Protocols for Agent Teams",
                "authors": ["N. Researcher"],
                "year": 2026,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2601.00001",
                "category": "social memory protocol",
                "contribution": (
                    "Defines provenance-aware memory exchange protocols "
                    "for collaborative agents."
                ),
                "evidence": "metadata verified",
                "tags": ["social memory", "provenance", "multi-agent"],
            }
        ]
        search_report = SearchAgent().run(papers)

        draft = WriterAgent().run(search_report)

        body = draft.split("## References", 1)[0]
        self.assertIn("### Social Memory Protocol", body)
        self.assertIn("[new2026social]", body)
        self.assertIn("provenance-aware memory exchange protocols", body)

    def test_reviewer_flags_unknown_citations(self) -> None:
        papers = [
            {
                "citation_key": "packer2023memgpt",
                "title": "MemGPT: Towards LLMs as Operating Systems",
                "authors": ["Charles Packer"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2310.08560",
            }
        ]

        report = ReviewerAgent().review("This claim cites [fake2026paper].", papers)

        self.assertEqual(report["status"], "revise")
        self.assertEqual(report["unknown_citations"], ["fake2026paper"])

    def test_reviewer_and_final_gate_detect_extended_unknown_keys(self) -> None:
        papers = [
            {
                "citation_key": "packer2023memgpt",
                "title": "MemGPT: Towards LLMs as Operating Systems",
                "authors": ["Charles Packer"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2310.08560",
                "category": "memory mechanism",
                "contribution": "Introduces virtual context management.",
                "evidence": "verified",
                "tags": ["memory"],
            }
        ]
        markdown = (
            "## Abstract\n"
            "A fabricated claim cites [unknown_key].\n\n"
            "## Implications for Multi-Agent Literature Review Systems\n"
            "Evidence remains traceable.\n\n"
            "## References\n"
        )

        reviewer = ReviewerAgent().review(markdown, papers)
        final = FinalVerificationReviewer().review(markdown, markdown, papers)

        self.assertEqual(reviewer["unknown_citations"], ["unknown_key"])
        self.assertEqual(reviewer["status"], "revise")
        self.assertEqual(final["unknown_citations"], ["unknown_key"])
        self.assertEqual(final["status"], "revise")

    def test_reviewer_flags_real_citation_when_claim_is_not_supported(self) -> None:
        papers = [
            {
                "citation_key": "packer2023memgpt",
                "title": "MemGPT: Towards LLMs as Operating Systems",
                "authors": ["Charles Packer"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2310.08560",
                "category": "memory mechanism",
                "contribution": "Introduces virtual context management for long-running LLM agents.",
                "evidence": "verified",
                "tags": ["hierarchical memory", "virtual context"],
            }
        ]

        report = ReviewerAgent().review(
            "MemGPT introduced MemoryAgentBench for incremental multi-turn evaluation [packer2023memgpt].",
            papers,
        )

        self.assertEqual(report["status"], "revise")
        self.assertEqual(report["unknown_citations"], [])
        self.assertEqual(len(report["unsupported_claims"]), 1)
        self.assertIn("MemoryAgentBench", report["unsupported_claims"][0]["sentence"])

    def test_orchestrator_passes_reviewer_feedback_back_to_writer(self) -> None:
        class FeedbackAwareWriter:
            def __init__(self) -> None:
                self.received_feedback = []

            def run(self, search_report, review_feedback=None):
                self.received_feedback.append(review_feedback)
                if review_feedback is None:
                    return (
                        "# Draft\n\n"
                        "## Abstract\n"
                        "Bad citation [fake2026paper].\n\n"
                        "## Implications for Multi-Agent Literature Review Systems\n"
                        "Bad citation [fake2026paper].\n\n"
                        "## References\n"
                    )
                return (
                    "# Draft\n\n"
                    "## Abstract\n"
                    "MemGPT introduces virtual context management [packer2023memgpt].\n\n"
                    "## Implications for Multi-Agent Literature Review Systems\n"
                    "A revised draft removes unsupported citations.\n\n"
                    "## References\n"
                    "- [packer2023memgpt] Charles Packer (2023). MemGPT.\n"
                )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "papers.json"
            output_dir = root / "outputs"
            write_sample_corpus(corpus)
            writer = FeedbackAwareWriter()
            orchestrator = Orchestrator(corpus_path=corpus, output_dir=output_dir)
            orchestrator.writer_agent = writer

            result = orchestrator.run()

            self.assertEqual(result["status"], "accepted")
            self.assertIsNone(writer.received_feedback[0])
            self.assertEqual(
                writer.received_feedback[1]["unknown_citations"],
                ["fake2026paper"],
            )

    def test_orchestrator_revalidates_safe_draft_after_rejected_polish(self) -> None:
        class CitationDroppingPolisher:
            def run(self, markdown: str) -> str:
                return markdown.replace("[packer2023memgpt]", "")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "papers.json"
            output_dir = root / "outputs"
            write_sample_corpus(corpus)
            orchestrator = Orchestrator(corpus_path=corpus, output_dir=output_dir)
            orchestrator.polish_agent = CitationDroppingPolisher()

            result = orchestrator.run()

            verification = json.loads(
                (output_dir / "final_verification.json").read_text(
                    encoding="utf-8"
                )
            )
            survey = (output_dir / "survey.md").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "accepted")
            self.assertEqual(verification["status"], "accepted")
            self.assertEqual(
                verification["final_action"],
                "polish_output_rejected; accepted draft retained",
            )
            self.assertEqual(
                verification["rejected_polish_verification"]["status"],
                "revise",
            )
            self.assertIn("[packer2023memgpt]", survey)

    def test_final_verification_rejects_polish_added_citation(self) -> None:
        papers = [
            {
                "citation_key": "packer2023memgpt",
                "title": "MemGPT: Towards LLMs as Operating Systems",
                "authors": ["Charles Packer"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2310.08560",
                "category": "memory mechanism",
                "contribution": "Introduces virtual context management for long-running LLM agents.",
                "evidence": "verified",
                "tags": ["hierarchical memory", "virtual context"],
            }
        ]
        accepted_draft = (
            "## Abstract\n"
            "MemGPT introduces virtual context management [packer2023memgpt].\n\n"
            "## Implications for Multi-Agent Literature Review Systems\n"
            "Verified memory should remain traceable.\n\n"
            "## References\n"
        )
        polished = accepted_draft.replace(
            "Verified memory should remain traceable.",
            "Verified memory should remain traceable [fake2026paper].",
        )

        report = FinalVerificationReviewer().review(accepted_draft, polished, papers)

        self.assertEqual(report["status"], "revise")
        self.assertEqual(report["new_citations_after_polish"], ["fake2026paper"])
        self.assertEqual(report["unknown_citations"], ["fake2026paper"])

    def test_final_verification_rejects_polish_removed_citation(self) -> None:
        papers = [
            {
                "citation_key": "packer2023memgpt",
                "title": "MemGPT: Towards LLMs as Operating Systems",
                "authors": ["Charles Packer"],
                "year": 2023,
                "venue": "arXiv",
                "url": "https://arxiv.org/abs/2310.08560",
                "category": "memory mechanism",
                "contribution": "Introduces virtual context management for agents.",
                "evidence": "verified",
                "tags": ["memory", "virtual context"],
            }
        ]
        accepted_draft = (
            "## Abstract\n"
            "MemGPT introduces virtual context management [packer2023memgpt].\n\n"
            "## Implications for Multi-Agent Literature Review Systems\n"
            "Memory should remain traceable.\n\n"
            "## References\n"
        )
        polished = accepted_draft.replace(" [packer2023memgpt]", "")

        report = FinalVerificationReviewer().review(
            accepted_draft,
            polished,
            papers,
        )

        self.assertEqual(report["status"], "revise")
        self.assertEqual(
            report["removed_citations_after_polish"],
            ["packer2023memgpt"],
        )
        self.assertIn("removed citations", " ".join(report["recommendations"]))

    def test_runtime_config_defaults_to_deterministic_without_env(self) -> None:
        config = AgentRuntimeConfig.from_env({})

        self.assertEqual(config.backend, "deterministic")
        self.assertFalse(config.api_enabled)
        self.assertEqual(config.api_mode, "single")

    def test_runtime_config_rejects_unknown_backend(self) -> None:
        with self.assertRaisesRegex(AgentConfigurationError, "AGENT_BACKEND"):
            AgentRuntimeConfig.from_env({"AGENT_BACKEND": "apis"})

    def test_runtime_config_rejects_incomplete_api_backend(self) -> None:
        with self.assertRaisesRegex(AgentConfigurationError, "AGENT_MODEL"):
            AgentRuntimeConfig.from_env(
                {
                    "AGENT_BACKEND": "api",
                    "AGENT_API_BASE_URL": "https://api.example.com/v1",
                    "AGENT_API_KEY": "shared-key",
                }
            )

    def test_runtime_config_rejects_api_fields_without_api_backend(self) -> None:
        with self.assertRaisesRegex(AgentConfigurationError, "AGENT_BACKEND=api"):
            AgentRuntimeConfig.from_env(
                {
                    "AGENT_API_BASE_URL": "https://api.example.com/v1",
                    "AGENT_API_KEY": "shared-key",
                    "AGENT_MODEL": "shared-model",
                }
            )

    def test_runtime_config_rejects_insecure_remote_api_url(self) -> None:
        with self.assertRaisesRegex(AgentConfigurationError, "HTTPS"):
            AgentRuntimeConfig.from_env(
                {
                    "AGENT_BACKEND": "api",
                    "AGENT_API_BASE_URL": "http://api.example.com/v1",
                    "AGENT_API_KEY": "shared-key",
                    "AGENT_MODEL": "shared-model",
                }
            )

    def test_runtime_config_allows_loopback_http_api_url(self) -> None:
        config = AgentRuntimeConfig.from_env(
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_BASE_URL": "http://127.0.0.1:11434/v1",
                "AGENT_API_KEY": "local-key",
                "AGENT_MODEL": "local-model",
            }
        )

        self.assertTrue(config.api_enabled)

    def test_runtime_config_rejects_unsafe_numeric_ranges(self) -> None:
        base = {
            "AGENT_BACKEND": "api",
            "AGENT_API_BASE_URL": "https://api.example.com/v1",
            "AGENT_API_KEY": "shared-key",
            "AGENT_MODEL": "shared-model",
        }
        cases = (
            ({"AGENT_TEMPERATURE": "2.1"}, "AGENT_TEMPERATURE"),
            ({"AGENT_TIMEOUT_SECONDS": "0"}, "AGENT_TIMEOUT_SECONDS"),
            ({"WRITER_AGENT_TEMPERATURE": "invalid"}, "WRITER_AGENT_TEMPERATURE"),
        )
        for changes, message in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(AgentConfigurationError, message):
                    AgentRuntimeConfig.from_env({**base, **changes})

    def test_runtime_config_single_api_applies_defaults_to_all_agents(self) -> None:
        config = AgentRuntimeConfig.from_env(
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_MODE": "single",
                "AGENT_API_BASE_URL": "https://api.example.com/v1",
                "AGENT_API_KEY": "shared-key",
                "AGENT_MODEL": "shared-model",
                "AGENT_TEMPERATURE": "0.3",
            }
        )

        writer = config.for_agent("writer")
        reviewer = config.for_agent("reviewer")

        self.assertTrue(config.api_enabled)
        self.assertEqual(config.api_mode, "single")
        self.assertEqual(writer.model, "shared-model")
        self.assertEqual(reviewer.model, "shared-model")
        self.assertEqual(writer.temperature, 0.3)
        self.assertTrue(writer.api_enabled)

    def test_runtime_config_multi_api_allows_agent_overrides(self) -> None:
        config = AgentRuntimeConfig.from_env(
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_MODE": "multi",
                "AGENT_API_BASE_URL": "https://api.example.com/v1",
                "AGENT_API_KEY": "shared-key",
                "AGENT_MODEL": "shared-model",
                "AGENT_TEMPERATURE": "0.2",
                "WRITER_AGENT_MODEL": "writer-model",
                "WRITER_AGENT_TEMPERATURE": "0.5",
                "REVIEWER_AGENT_API_KEY": "reviewer-key",
                "REVIEWER_AGENT_MODEL": "reviewer-model",
                "REVIEWER_AGENT_TEMPERATURE": "0.0",
            }
        )

        writer = config.for_agent("writer")
        reviewer = config.for_agent("reviewer")
        search = config.for_agent("search")

        self.assertEqual(config.api_mode, "multi")
        self.assertEqual(writer.model, "writer-model")
        self.assertEqual(writer.api_key, "shared-key")
        self.assertEqual(writer.temperature, 0.5)
        self.assertEqual(reviewer.model, "reviewer-model")
        self.assertEqual(reviewer.api_key, "reviewer-key")
        self.assertEqual(reviewer.temperature, 0.0)
        self.assertEqual(search.model, "shared-model")

    def test_reflection_markdown_formats_scores_consistently(self) -> None:
        report = {
            "final_status": "accepted",
            "records_included": 17,
            "revision_iterations": 1,
            "scores": {
                "citation_integrity": 5,
                "claim_source_alignment": 5,
                "process_control": 5,
                "literature_coverage": 5,
                "overall": 5.0,
            },
            "reflections": [],
            "next_run_improvements": [],
        }

        markdown = EvaluationReflectionAgent().to_markdown(report)

        self.assertIn("- citation_integrity: 5.0/5.0", markdown)
        self.assertIn("- overall: 5.0/5.0", markdown)


if __name__ == "__main__":
    unittest.main()
