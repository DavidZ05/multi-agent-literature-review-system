from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from src.literature_review.api import OpenAIChatClient
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery import (
    ApprovalService,
    DiscoveryService,
    QueryPlanner,
)
from src.literature_review.models import WorkflowStage
from src.literature_review.plugins import (
    AgentFactory,
    ProviderContext,
    ProviderPluginError,
    ProviderRegistry,
    build_agent_factory,
    build_provider_registry,
)
from src.literature_review.providers import (
    UrllibHttpTransport,
)
from src.literature_review.storage import (
    LocalArtifactStore,
    SQLiteResponseCache,
    SQLiteWorkflowStore,
)
from src.literature_review.workflow import (
    ApprovalGateHandler,
    DiscoveryHandler,
    DraftingHandler,
    PersistentWorkflowEngine,
    PlanningHandler,
    ScreeningHandler,
)

def build_engine(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
    *,
    discovery_enabled: bool = False,
    providers: tuple[str, ...] = ("arxiv", "semantic_scholar"),
    max_results: int = 10,
    api_client: Any | None = None,
    provider_registry: ProviderRegistry | None = None,
    agent_factory: AgentFactory | None = None,
    environment: Mapping[str, str] | None = None,
) -> PersistentWorkflowEngine:
    environment = os.environ if environment is None else environment
    provider_registry = provider_registry or build_provider_registry()
    agent_factory = agent_factory or build_agent_factory()
    runtime_config = AgentRuntimeConfig.from_env(environment)
    if runtime_config.active_backend == "api" and api_client is None:
        api_client = OpenAIChatClient()
    handlers = {
        WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=discovery_enabled),
        WorkflowStage.DRAFTING: DraftingHandler(
            runtime_config,
            api_client=api_client,
            agent_factory=agent_factory,
        ),
    }
    workflow_config = runtime_config.public_dict()
    selected_provider_plugins = [
        option
        for option in provider_registry.options()
        if discovery_enabled and option["id"] in providers
    ]
    workflow_config.update(
        {
            "discovery_enabled": discovery_enabled,
            "discovery_providers": list(providers),
            "discovery_max_results": max_results,
            "provider_plugins": selected_provider_plugins,
            "agent_plugins": agent_factory.manifest(),
        }
    )
    if discovery_enabled:
        transport = UrllibHttpTransport()
        cache = SQLiteResponseCache(store.path)
        context = ProviderContext(transport, cache, environment)
        provider_instances = {
            provider_id: provider_registry.create(provider_id, context)
            for provider_id in providers
        }
        approval = ApprovalService(store)
        handlers.update(
            {
                WorkflowStage.DISCOVERING: DiscoveryHandler(
                    DiscoveryService(
                        QueryPlanner(max_results=max_results),
                        provider_instances,
                    )
                ),
                WorkflowStage.SCREENING: ScreeningHandler(),
                WorkflowStage.AWAITING_CORPUS_APPROVAL: ApprovalGateHandler(approval),
            }
        )
    return PersistentWorkflowEngine(
        store,
        LocalArtifactStore(artifact_root),
        handlers,
        runtime_config=workflow_config,
    )


def load_resume_settings(
    artifact_store: LocalArtifactStore,
    run_id: str,
    *,
    provider_registry: ProviderRegistry | None = None,
) -> tuple[bool, tuple[str, ...], int]:
    request = artifact_store.read_json(run_id, "inputs/research_request.json")
    if not isinstance(request, dict):
        raise TypeError("stored research request must be an object")
    config = request.get("runtime_config", {})
    if not isinstance(config, dict):
        raise TypeError("stored runtime_config must be an object")

    enabled = config.get("discovery_enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("stored discovery_enabled must be a boolean")

    provider_values = config.get(
        "discovery_providers",
        ("arxiv", "semantic_scholar"),
    )
    if (
        not isinstance(provider_values, (list, tuple))
        or any(not isinstance(provider, str) for provider in provider_values)
    ):
        raise TypeError("stored discovery_providers must be a list of strings")
    providers = tuple(provider_values)
    provider_registry = provider_registry or build_provider_registry()
    unknown_providers = set(providers) - set(provider_registry.names())
    if unknown_providers:
        unknown = sorted(unknown_providers)[0]
        raise ProviderPluginError(
            f"stored discovery_providers contains unavailable provider: {unknown}"
        )
    if enabled and not providers:
        raise ValueError("stored discovery_providers must be nonempty")

    max_results = config.get("discovery_max_results", 10)
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise TypeError("stored discovery_max_results must be an integer")
    if not 1 <= max_results <= 50:
        raise ValueError("stored discovery_max_results must be between 1 and 50")
    return enabled, providers, max_results


__all__ = ["build_engine", "load_resume_settings"]
