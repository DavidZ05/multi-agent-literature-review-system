import json
import tempfile
import unittest
from pathlib import Path


class ModuleBoundaryTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        from src import literature_review

        self.assertEqual(literature_review.__version__, "0.1.0")
        self.assertEqual(
            literature_review.__all__,
            [
                "main",
                "AgentAPISettings",
                "AgentRuntimeConfig",
                "PROJECT_TITLE",
                "citation_label",
                "first_author_last_name",
                "load_papers",
                "EvaluationReflectionAgent",
                "Orchestrator",
                "DomainExpertAgent",
                "FinalVerificationReviewer",
                "ReviewerAgent",
                "ReviewSynthesizerAgent",
                "StructureMentorAgent",
                "SearchAgent",
                "PolishAgent",
                "WriterAgent",
                "CandidatePaper",
                "CandidateStatus",
                "CorpusDecision",
                "ProviderPaper",
                "ProviderSearchResult",
                "ResearchRun",
                "RunStatus",
                "ScreeningRecommendation",
                "SearchQuery",
                "WorkflowStage",
                "WorkflowEvent",
                "StageCheckpoint",
                "utc_now_iso",
            ],
        )

    def test_legacy_imports_preserve_object_identity(self) -> None:
        from src.literature_review.base import RuntimeAwareAgent
        from src.literature_review.config import (
            AgentAPISettings,
            AgentRuntimeConfig,
        )
        from src.memory_review_pipeline import (
            AgentAPISettings as LegacyAgentAPISettings,
            AgentRuntimeConfig as LegacyAgentRuntimeConfig,
            RuntimeAwareAgent as LegacyRuntimeAwareAgent,
        )

        self.assertIs(LegacyAgentAPISettings, AgentAPISettings)
        self.assertIs(LegacyAgentRuntimeConfig, AgentRuntimeConfig)
        self.assertIs(LegacyRuntimeAwareAgent, RuntimeAwareAgent)


class CompatibilityTests(unittest.TestCase):
    def test_legacy_module_reexports_new_public_api(self) -> None:
        from src import literature_review
        import src.memory_review_pipeline as legacy

        cases = [
            ("AgentAPISettings", literature_review.AgentAPISettings),
            ("AgentRuntimeConfig", literature_review.AgentRuntimeConfig),
            (
                "EvaluationReflectionAgent",
                literature_review.EvaluationReflectionAgent,
            ),
            (
                "FinalVerificationReviewer",
                literature_review.FinalVerificationReviewer,
            ),
            ("Orchestrator", literature_review.Orchestrator),
            ("ReviewerAgent", literature_review.ReviewerAgent),
            ("SearchAgent", literature_review.SearchAgent),
            ("load_papers", literature_review.load_papers),
        ]

        for name, canonical in cases:
            with self.subTest(name=name):
                self.assertIs(getattr(legacy, name), canonical)


class OrchestratorModuleTests(unittest.TestCase):
    def test_orchestrator_is_defined_in_new_module(self) -> None:
        import src.memory_review_pipeline as legacy
        from src.literature_review.cli import main as cli_main
        from src.literature_review.orchestrator import Orchestrator

        self.assertEqual(Orchestrator.__module__, "src.literature_review.orchestrator")
        self.assertIs(legacy.Orchestrator, Orchestrator)
        self.assertIs(legacy.main, cli_main)

    def test_legacy_pipeline_declares_explicit_exports(self) -> None:
        import src.memory_review_pipeline as legacy

        self.assertEqual(
            legacy.__all__,
            [
                "RuntimeAwareAgent",
                "AgentAPISettings",
                "AgentRuntimeConfig",
                "main",
                "PROJECT_TITLE",
                "citation_label",
                "first_author_last_name",
                "load_papers",
                "EvaluationReflectionAgent",
                "Orchestrator",
                "DomainExpertAgent",
                "FinalVerificationReviewer",
                "ReviewerAgent",
                "ReviewSynthesizerAgent",
                "StructureMentorAgent",
                "SearchAgent",
                "PolishAgent",
                "WriterAgent",
            ],
        )


class ReviewModuleTests(unittest.TestCase):
    def test_review_module_exposes_complete_panel(self) -> None:
        from src.literature_review.evaluation import EvaluationReflectionAgent
        from src.literature_review.review import (
            DomainExpertAgent,
            FinalVerificationReviewer,
            ReviewerAgent,
            ReviewSynthesizerAgent,
            StructureMentorAgent,
        )
        from src.memory_review_pipeline import (
            DomainExpertAgent as LegacyDomainExpertAgent,
            EvaluationReflectionAgent as LegacyEvaluationReflectionAgent,
            FinalVerificationReviewer as LegacyFinalVerificationReviewer,
            ReviewerAgent as LegacyReviewerAgent,
            ReviewSynthesizerAgent as LegacyReviewSynthesizerAgent,
            StructureMentorAgent as LegacyStructureMentorAgent,
        )

        class_names = {
            ReviewerAgent.__name__,
            DomainExpertAgent.__name__,
            StructureMentorAgent.__name__,
            ReviewSynthesizerAgent.__name__,
            FinalVerificationReviewer.__name__,
            EvaluationReflectionAgent.__name__,
        }

        self.assertEqual(len(class_names), 6)
        self.assertIs(LegacyReviewerAgent, ReviewerAgent)
        self.assertIs(LegacyDomainExpertAgent, DomainExpertAgent)
        self.assertIs(LegacyStructureMentorAgent, StructureMentorAgent)
        self.assertIs(LegacyReviewSynthesizerAgent, ReviewSynthesizerAgent)
        self.assertIs(LegacyFinalVerificationReviewer, FinalVerificationReviewer)
        self.assertIs(LegacyEvaluationReflectionAgent, EvaluationReflectionAgent)


class ConfigModuleTests(unittest.TestCase):
    def test_config_module_resolves_agent_override(self) -> None:
        from src.literature_review.config import AgentRuntimeConfig

        config = AgentRuntimeConfig.from_env(
            {
                "AGENT_BACKEND": "api",
                "AGENT_API_MODE": "multi",
                "AGENT_API_BASE_URL": "https://api.example.com/v1",
                "AGENT_API_KEY": "shared-key",
                "AGENT_MODEL": "default-model",
                "WRITER_AGENT_MODEL": "writer-model",
            }
        )

        writer = config.for_agent("writer")
        reviewer = config.for_agent("reviewer")

        self.assertEqual(writer.model, "writer-model")
        self.assertEqual(reviewer.model, "default-model")
        self.assertEqual(config.public_dict()["api_key"], "<configured>")

    def test_concrete_agents_expose_expected_agent_ids(self) -> None:
        from src.memory_review_pipeline import (
            DomainExpertAgent,
            EvaluationReflectionAgent,
            FinalVerificationReviewer,
            PolishAgent,
            ReviewSynthesizerAgent,
            ReviewerAgent,
            SearchAgent,
            StructureMentorAgent,
            WriterAgent,
        )

        cases = [
            (SearchAgent, "search"),
            (WriterAgent, "writer"),
            (ReviewerAgent, "reviewer"),
            (DomainExpertAgent, "domain_expert"),
            (StructureMentorAgent, "structure_mentor"),
            (ReviewSynthesizerAgent, "review_synthesizer"),
            (PolishAgent, "polish"),
            (FinalVerificationReviewer, "final_verification"),
            (EvaluationReflectionAgent, "evaluation_reflection"),
        ]

        for agent_cls, expected_agent_id in cases:
            with self.subTest(agent_cls=agent_cls.__name__):
                self.assertEqual(agent_cls().agent_id, expected_agent_id)


class WritingModuleTests(unittest.TestCase):
    def test_search_and_writer_are_available_from_new_modules(self) -> None:
        from src.literature_review.search import SearchAgent
        from src.literature_review.writing import PolishAgent, WriterAgent

        self.assertEqual(SearchAgent.__name__, "SearchAgent")
        self.assertEqual(WriterAgent.__name__, "WriterAgent")
        self.assertEqual(PolishAgent.__name__, "PolishAgent")
        self.assertEqual(PolishAgent().run("Draft  text\n\n\n"), "Draft text\n")


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
