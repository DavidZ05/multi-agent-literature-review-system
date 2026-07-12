from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.plugins import (
    AgentPluginError,
    ProviderContext,
    ProviderPluginError,
    build_agent_factory,
    build_provider_registry,
)
from src.literature_review.review import ReviewerAgent
from src.literature_review.runtime import build_engine
from src.literature_review.storage import SQLiteWorkflowStore


class FakeDistribution:
    name = "example-plugin"
    version = "1.2.3"


class FakeEntryPoint:
    def __init__(
        self,
        name: str,
        value: str,
        loaded: object,
        *,
        distribution: object | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self._loaded = loaded
        self.dist = distribution

    def load(self) -> object:
        if isinstance(self._loaded, BaseException):
            raise self._loaded
        return self._loaded


class CrossrefProvider:
    provider_id = "crossref"
    artifact_extension = "json"

    def search(self, query: object) -> object:
        return query

    def fetch_details(self, provider_id: str) -> object:
        return provider_id


def crossref_builder(context: ProviderContext) -> CrossrefProvider:
    del context
    return CrossrefProvider()


crossref_builder.plugin_label = "Crossref"  # type: ignore[attr-defined]


class CustomWriter:
    def __init__(self, config: AgentRuntimeConfig, client: object | None) -> None:
        self.config = config
        self.client = client
        self.agent_id = "unset"

    def run(self, report: object, review_feedback: object | None = None) -> str:
        del report, review_feedback
        return "custom draft"


def custom_writer_builder(
    config: AgentRuntimeConfig,
    client: object | None,
) -> CustomWriter:
    return CustomWriter(config, client)


class ProviderRegistryTests(unittest.TestCase):
    def test_builtin_and_entry_point_providers_share_registry(self) -> None:
        registry = build_provider_registry(
            entry_points=(
                FakeEntryPoint(
                    "crossref",
                    "example_plugin:crossref_builder",
                    crossref_builder,
                    distribution=FakeDistribution(),
                ),
            )
        )

        self.assertEqual(
            registry.names(),
            ("arxiv", "semantic_scholar", "crossref"),
        )
        self.assertEqual(registry.options()[-1]["label"], "Crossref")
        self.assertFalse(registry.options()[-1]["default_enabled"])
        self.assertTrue(registry.options()[0]["default_enabled"])
        self.assertEqual(
            registry.options()[-1]["source"],
            "entry_point:example_plugin:crossref_builder@example-plugin==1.2.3",
        )
        provider = registry.create(
            "crossref",
            ProviderContext(object(), object(), {}),  # type: ignore[arg-type]
        )
        self.assertIsInstance(provider, CrossrefProvider)

    def test_provider_ids_conflicts_and_load_failures_are_explicit(self) -> None:
        invalid_cases = ("Cross-Ref", "../provider", "", "1provider")
        for provider_id in invalid_cases:
            with self.subTest(provider_id=provider_id):
                registry = build_provider_registry(load_entry_points=False)
                with self.assertRaises(ProviderPluginError):
                    registry.register(provider_id, crossref_builder)

        with self.assertRaisesRegex(ProviderPluginError, "already registered"):
            build_provider_registry(
                entry_points=(
                    FakeEntryPoint("arxiv", "plugin:factory", crossref_builder),
                )
            )
        with self.assertRaisesRegex(ProviderPluginError, "failed to load"):
            build_provider_registry(
                entry_points=(
                    FakeEntryPoint("crossref", "plugin:factory", RuntimeError("boom")),
                )
            )


class AgentFactoryTests(unittest.TestCase):
    def test_replaceable_agent_uses_plugin_while_safety_agent_stays_builtin(self) -> None:
        factory = build_agent_factory(
            entry_points=(
                FakeEntryPoint(
                    "writer",
                    "example_plugin:custom_writer_builder",
                    custom_writer_builder,
                ),
            )
        )
        config = AgentRuntimeConfig()

        writer = factory.create("writer", config)
        reviewer = factory.create("reviewer", config)

        self.assertIsInstance(writer, CustomWriter)
        self.assertEqual(writer.agent_id, "writer")
        self.assertIsInstance(reviewer, ReviewerAgent)
        self.assertTrue(factory.manifest()["reviewer"]["protected"])
        self.assertIn("entry_point:", factory.manifest()["writer"]["source"])

    def test_plugins_cannot_replace_citation_safety_roles(self) -> None:
        for role in ("search", "reviewer", "final_verification"):
            with self.subTest(role=role):
                with self.assertRaisesRegex(AgentPluginError, "protected"):
                    build_agent_factory(
                        entry_points=(
                            FakeEntryPoint(role, "plugin:unsafe", custom_writer_builder),
                        )
                    )

    def test_multiple_plugins_cannot_silently_override_the_same_role(self) -> None:
        entries = (
            FakeEntryPoint("writer", "first:writer", custom_writer_builder),
            FakeEntryPoint("writer", "second:writer", custom_writer_builder),
        )

        with self.assertRaisesRegex(AgentPluginError, "already provided"):
            build_agent_factory(entry_points=entries)

    def test_orchestrator_accepts_injected_agent_factory(self) -> None:
        factory = build_agent_factory(load_entry_points=False)
        factory.register_plugin("writer", custom_writer_builder)
        with TemporaryDirectory() as temporary:
            orchestrator = Orchestrator(
                Path(temporary) / "papers.json",
                Path(temporary) / "outputs",
                agent_factory=factory,
            )

        self.assertIsInstance(orchestrator.writer_agent, CustomWriter)
        self.assertIsInstance(orchestrator.reviewer_agent, ReviewerAgent)

    def test_runtime_records_active_plugin_manifest(self) -> None:
        providers = build_provider_registry(
            entry_points=(
                FakeEntryPoint("crossref", "plugin:crossref", crossref_builder),
            )
        )
        agents = build_agent_factory(
            entry_points=(
                FakeEntryPoint("writer", "plugin:writer", custom_writer_builder),
            )
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SQLiteWorkflowStore(root / "workflow.db")
            engine = build_engine(
                store,
                root / "artifacts",
                discovery_enabled=True,
                providers=("crossref",),
                provider_registry=providers,
                agent_factory=agents,
                environment={},
            )

        self.assertEqual(
            [item["id"] for item in engine.runtime_config["provider_plugins"]],
            ["crossref"],
        )
        self.assertEqual(
            engine.runtime_config["agent_plugins"]["writer"]["source"],
            "entry_point:plugin:writer",
        )


if __name__ == "__main__":
    unittest.main()
