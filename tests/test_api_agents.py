from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.literature_review.api.prompts import PromptNotFoundError, load_prompt
from src.literature_review.api import APIResponseError
from src.literature_review.base import AgentBackendError
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.evaluation import EvaluationReflectionAgent
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.review import (
    DomainExpertAgent,
    ReviewSynthesizerAgent,
    StructureMentorAgent,
)
from src.literature_review.writing import PolishAgent, WriterAgent
from tests.test_pipeline import write_sample_corpus


class FakeClient:
    def __init__(self, responses: list[dict[str, object]] | None = None) -> None:
        self.calls = []
        self.responses = list(responses or [{"accepted": True}])

    def complete_json(self, settings, *, system_prompt, user_payload):
        self.calls.append((settings, system_prompt, user_payload))
        response = dict(self.responses.pop(0))
        response.setdefault("agent", settings.agent_id)
        return response


def api_runtime() -> AgentRuntimeConfig:
    return AgentRuntimeConfig.from_env(
        {
            "AGENT_BACKEND": "api",
            "AGENT_API_MODE": "single",
            "AGENT_API_BASE_URL": "https://api.example.com/v1",
            "AGENT_API_KEY": "shared-key",
            "AGENT_MODEL": "shared-model",
        }
    )


def search_report() -> dict[str, object]:
    papers = [
        {
            "citation_key": "packer2023memgpt",
            "title": "MemGPT",
            "authors": ["A. Author"],
            "year": 2023,
            "venue": "arXiv",
            "url": "https://arxiv.org/abs/2310.08560",
            "category": "memory mechanism",
            "contribution": "introduces virtual context memory",
        }
    ]
    return {
        "query": "Memory-Augmented LLM Agents",
        "records_included": 1,
        "grouped_papers": {"memory mechanism": papers},
    }


class APIDispatchTests(unittest.TestCase):
    def test_deterministic_backend_note_is_explicit(self) -> None:
        agent = WriterAgent(AgentRuntimeConfig())

        self.assertEqual(agent.backend_note(), "deterministic")

    def test_api_call_uses_agent_profile_and_injected_client(self) -> None:
        client = FakeClient()
        agent = WriterAgent(api_runtime(), api_client=client)

        result = agent.call_api("Return JSON.", {"draft": "text"})

        self.assertEqual(result, {"accepted": True, "agent": "writer"})
        settings, system_prompt, user_payload = client.calls[0]
        self.assertEqual(settings.agent_id, "writer")
        self.assertEqual(settings.model, "shared-model")
        self.assertEqual(system_prompt, "Return JSON.")
        self.assertEqual(user_payload, {"draft": "text"})

    def test_api_backend_requires_injected_client(self) -> None:
        agent = WriterAgent(api_runtime())

        with self.assertRaisesRegex(AgentBackendError, "API client"):
            agent.call_api("Return JSON.", {"draft": "text"})

    def test_api_call_rejects_non_object_payload(self) -> None:
        agent = WriterAgent(api_runtime(), api_client=FakeClient())

        with self.assertRaisesRegex(TypeError, "JSON object"):
            agent.call_api("Return JSON.", ["not", "an", "object"])

    def test_prompt_loader_reads_packaged_prompt_files(self) -> None:
        prompt = load_prompt("writer")

        self.assertIn("Return JSON", prompt)
        self.assertIn("citation", prompt.lower())

    def test_packaged_prompts_treat_payload_text_as_untrusted_data(self) -> None:
        for name in (
            "writer",
            "domain_expert",
            "structure_mentor",
            "review_synthesizer",
            "polish",
            "evaluation_reflection",
        ):
            with self.subTest(name=name):
                prompt = load_prompt(name).lower()
                self.assertIn("return json only", prompt)
                self.assertIn("not as instructions", prompt)

    def test_polish_prompt_requires_exact_citation_preservation(self) -> None:
        prompt = load_prompt("polish").lower()

        for rule in ("do not add", "remove", "rename", "citation-key set exactly"):
            with self.subTest(rule=rule):
                self.assertIn(rule, prompt)

    def test_writer_prompt_requires_complete_grounded_markdown(self) -> None:
        prompt = load_prompt("writer").lower()

        self.assertIn("complete literature review", prompt)
        self.assertIn("search_report", prompt)
        self.assertIn("review_feedback", prompt)
        self.assertIn("citation_allowlist", prompt)

    def test_prompt_loader_rejects_missing_prompt_files(self) -> None:
        with self.assertRaises(PromptNotFoundError):
            load_prompt("missing-prompt")


class APIWritingAgentTests(unittest.TestCase):
    def test_writer_api_uses_review_feedback_and_citation_allowlist(self) -> None:
        markdown = "# Draft\n\nMemGPT supports memory [packer2023memgpt].\n"
        client = FakeClient(
            [{"markdown": markdown, "change_summary": "Used reviewer feedback."}]
        )
        agent = WriterAgent(api_runtime(), api_client=client)

        result = agent.run(
            search_report(),
            review_feedback={"unsupported_claims": ["tighten evidence"]},
        )

        self.assertEqual(result, markdown)
        settings, system_prompt, payload = client.calls[0]
        self.assertEqual(settings.agent_id, "writer")
        self.assertIn("Return JSON", system_prompt)
        self.assertEqual(payload["citation_allowlist"], ["packer2023memgpt"])
        self.assertEqual(payload["review_feedback"], {"unsupported_claims": ["tighten evidence"]})

    def test_writer_api_rejects_unknown_citation(self) -> None:
        client = FakeClient(
            [{"markdown": "Bad citation [fake_2026].", "change_summary": "none"}]
        )
        agent = WriterAgent(api_runtime(), api_client=client)

        with self.assertRaises(APIResponseError) as raised:
            agent.run(search_report())

        self.assertEqual(raised.exception.code, "unknown_citation")

    def test_writer_api_rejects_invalid_schema(self) -> None:
        client = FakeClient([{"change_summary": "missing markdown"}])
        agent = WriterAgent(api_runtime(), api_client=client)

        with self.assertRaises(APIResponseError) as raised:
            agent.run(search_report())

        self.assertEqual(raised.exception.code, "invalid_agent_output")

    def test_polish_api_returns_markdown_without_new_citations(self) -> None:
        client = FakeClient(
            [
                {
                    "markdown": "# Draft\n\nTighter wording [packer2023memgpt].\n",
                    "change_summary": "Polished only.",
                }
            ]
        )
        agent = PolishAgent(api_runtime(), api_client=client)

        result = agent.run("# Draft\n\nRaw wording [packer2023memgpt].\n")

        self.assertIn("Tighter wording", result)
        settings, system_prompt, payload = client.calls[0]
        self.assertEqual(settings.agent_id, "polish")
        self.assertIn("Return JSON", system_prompt)
        self.assertEqual(payload["citation_allowlist"], ["packer2023memgpt"])

    def test_polish_api_rejects_introduced_citation(self) -> None:
        client = FakeClient(
            [
                {
                    "markdown": "# Draft\n\nNew citation [fake2026paper].\n",
                    "change_summary": "Added citation.",
                }
            ]
        )
        agent = PolishAgent(api_runtime(), api_client=client)

        with self.assertRaises(APIResponseError) as raised:
            agent.run("# Draft\n\nRaw wording [packer2023memgpt].\n")

        self.assertEqual(raised.exception.code, "introduced_citation")


class APIExpertAgentTests(unittest.TestCase):
    def test_domain_expert_api_preserves_report_contract(self) -> None:
        client = FakeClient(
            [
                {
                    "status": "advisory",
                    "coverage": {"memory mechanisms": True},
                    "missing_or_weak_areas": ["evaluation"],
                    "recommendations": ["Add evaluation benchmarks."],
                }
            ]
        )
        agent = DomainExpertAgent(api_runtime(), api_client=client)

        report = agent.review("# Draft", [], search_report())

        self.assertEqual(report["agent"], "Domain Expert Agent")
        self.assertEqual(report["backend"], "api")
        self.assertEqual(report["status"], "advisory")
        self.assertEqual(report["paper_count_reviewed"], 0)
        self.assertEqual(report["categories_reviewed"], ["memory mechanism"])
        self.assertEqual(report["recommendations"], ["Add evaluation benchmarks."])

    def test_structure_mentor_api_preserves_report_contract(self) -> None:
        client = FakeClient(
            [
                {
                    "status": "accepted",
                    "word_count": 1200,
                    "missing_headings": [],
                    "recommendations": ["Structure is clear."],
                }
            ]
        )
        agent = StructureMentorAgent(api_runtime(), api_client=client)

        report = agent.review("# Draft")

        self.assertEqual(report["agent"], "Structure Mentor Agent")
        self.assertEqual(report["backend"], "api")
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["word_count"], 1200)
        self.assertEqual(report["missing_headings"], [])

    def test_expert_api_rejects_invalid_schema(self) -> None:
        agent = DomainExpertAgent(api_runtime(), api_client=FakeClient([{"status": "ok"}]))

        with self.assertRaises(APIResponseError) as raised:
            agent.review("# Draft", [], search_report())

        self.assertEqual(raised.exception.code, "invalid_agent_output")

    def test_synthesizer_api_cannot_clear_blocking_citation_findings(self) -> None:
        client = FakeClient(
            [
                {
                    "status": "accepted",
                    "blocking_agents": [],
                    "must_fix": [],
                    "should_fix": ["Keep the structure."],
                    "iteration_stop_rule": "model stop rule",
                }
            ]
        )
        agent = ReviewSynthesizerAgent(api_runtime(), api_client=client)
        citation_review = {
            "agent": "Citation Auditor Agent",
            "status": "revise",
            "recommendations": ["Remove unknown citations."],
        }
        domain_review = {
            "agent": "Domain Expert Agent",
            "status": "accepted",
            "recommendations": ["Coverage is adequate."],
        }

        report = agent.synthesize([citation_review, domain_review])

        self.assertEqual(report["status"], "revise")
        self.assertEqual(report["blocking_agents"], ["Citation Auditor Agent"])
        self.assertIn(
            "Citation Auditor Agent: Remove unknown citations.",
            report["must_fix"],
        )
        self.assertIn("Keep the structure.", report["should_fix"])


class APIReflectionAgentTests(unittest.TestCase):
    def test_reflection_api_preserves_advisory_report_contract(self) -> None:
        client = FakeClient(
            [
                {
                    "scores": {
                        "citation_integrity": 4.5,
                        "claim_source_alignment": 4.0,
                        "process_control": 5.0,
                        "literature_coverage": 3.5,
                        "overall": 4.25,
                    },
                    "final_status": "accepted",
                    "reflections": ["Keep citation gates deterministic."],
                    "next_run_improvements": ["Add more source coverage."],
                }
            ]
        )
        agent = EvaluationReflectionAgent(api_runtime(), api_client=client)
        final_verification = {
            "status": "revise",
            "unknown_citations": ["fake2026paper"],
            "unsupported_claims": [],
        }

        report = agent.evaluate(search_report(), {}, final_verification, [{"iteration": 1}])

        self.assertEqual(report["agent"], "Evaluation / Reflection Agent")
        self.assertEqual(report["backend"], "api")
        self.assertEqual(report["final_status"], "revise")
        self.assertEqual(report["revision_iterations"], 1)
        self.assertEqual(report["records_included"], 1)
        self.assertEqual(report["scores"]["overall"], 4.25)
        self.assertEqual(report["reflections"], ["Keep citation gates deterministic."])

    def test_reflection_api_rejects_out_of_range_scores(self) -> None:
        client = FakeClient(
            [
                {
                    "scores": {
                        "citation_integrity": 6.0,
                        "claim_source_alignment": 4.0,
                        "process_control": 5.0,
                        "literature_coverage": 3.5,
                        "overall": 4.25,
                    },
                    "reflections": ["Too generous."],
                    "next_run_improvements": ["Tighten scoring."],
                }
            ]
        )
        agent = EvaluationReflectionAgent(api_runtime(), api_client=client)

        with self.assertRaises(APIResponseError) as raised:
            agent.evaluate(
                search_report(),
                {},
                {"status": "accepted", "unknown_citations": [], "unsupported_claims": []},
                [],
            )

        self.assertEqual(raised.exception.code, "invalid_agent_output")


class APIOrchestratorTests(unittest.TestCase):
    def test_orchestrator_executes_six_model_backed_agents_with_shared_client(self) -> None:
        markdown = (
            "# Memory-Augmented LLM Agents: Mechanisms, Evaluation, and Reliability in Multi-Agent Systems\n\n"
            "## Abstract\n"
            "MemGPT introduces virtual context management for long-running LLM agents [packer2023memgpt].\n"
            "Reflexion stores verbal reflections in episodic memory for later trials [shinn2023reflexion].\n\n"
            "## 1. Introduction\n"
            "Memory-augmented LLM agents use verified source traces for continuity.\n\n"
            "## 2. Methodology\n"
            "The corpus contains screened memory papers.\n\n"
            "## 3. Taxonomy of Agent Memory\n"
            "Memory mechanisms include hierarchical memory and reflective memory.\n\n"
            "## 5. Evaluation\n"
            "Evaluation remains linked to screened source records.\n\n"
            "## 6. Reliability Risks\n"
            "Citation hallucination is controlled through deterministic gates.\n\n"
            "## 7. Implications for Multi-Agent Literature Review Systems\n"
            "Teams should share only approved evidence.\n\n"
            "## References\n"
            "- [packer2023memgpt] Charles Packer and Sarah Wooders (2023). MemGPT.\n"
            "- [shinn2023reflexion] Noah Shinn and Federico Cassano (2023). Reflexion.\n"
        )
        client = FakeClient(
            [
                {"markdown": markdown, "change_summary": "Drafted from allowlisted sources."},
                {
                    "status": "accepted",
                    "coverage": {"memory mechanisms": True},
                    "missing_or_weak_areas": [],
                    "recommendations": ["Coverage is suitable."],
                },
                {
                    "status": "accepted",
                    "word_count": 320,
                    "missing_headings": [],
                    "recommendations": ["Structure is suitable."],
                },
                {
                    "status": "accepted",
                    "blocking_agents": [],
                    "must_fix": [],
                    "should_fix": ["Proceed to polish."],
                    "iteration_stop_rule": "Stop when no blocking reviewer remains.",
                },
                {"markdown": markdown, "change_summary": "Polished without citation changes."},
                {
                    "scores": {
                        "citation_integrity": 5.0,
                        "claim_source_alignment": 5.0,
                        "process_control": 5.0,
                        "literature_coverage": 4.0,
                        "overall": 4.75,
                    },
                    "reflections": ["Deterministic gates protected citation integrity."],
                    "next_run_improvements": ["Add full-text checking for high-risk claims."],
                },
            ]
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "papers.json"
            output_dir = root / "outputs"
            write_sample_corpus(corpus)

            result = Orchestrator(
                corpus_path=corpus,
                output_dir=output_dir,
                runtime_config=api_runtime(),
                api_client=client,
            ).run()

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(
            [settings.agent_id for settings, _prompt, _payload in client.calls],
            [
                "writer",
                "domain_expert",
                "structure_mentor",
                "review_synthesizer",
                "polish",
                "evaluation_reflection",
            ],
        )


if __name__ == "__main__":
    unittest.main()
