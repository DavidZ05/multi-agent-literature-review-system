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
    load_papers,
)


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

    def test_runtime_config_defaults_to_deterministic_without_env(self) -> None:
        config = AgentRuntimeConfig.from_env({})

        self.assertEqual(config.backend, "deterministic")
        self.assertFalse(config.api_enabled)
        self.assertEqual(config.api_mode, "single")

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
