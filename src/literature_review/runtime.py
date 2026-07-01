from __future__ import annotations

import os
from pathlib import Path

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery import (
    ApprovalService,
    DiscoveryService,
    QueryPlanner,
)
from src.literature_review.models import WorkflowStage
from src.literature_review.providers import (
    ArxivProvider,
    SemanticScholarProvider,
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

_DISCOVERY_PROVIDERS = frozenset({"arxiv", "semantic_scholar"})


def build_engine(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
    *,
    discovery_enabled: bool = False,
    providers: tuple[str, ...] = ("arxiv", "semantic_scholar"),
    max_results: int = 10,
) -> PersistentWorkflowEngine:
    runtime_config = AgentRuntimeConfig.from_env()
    handlers = {
        WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=discovery_enabled),
        WorkflowStage.DRAFTING: DraftingHandler(runtime_config),
    }
    workflow_config = runtime_config.public_dict()
    workflow_config.update(
        {
            "discovery_enabled": discovery_enabled,
            "discovery_providers": list(providers),
            "discovery_max_results": max_results,
        }
    )
    if discovery_enabled:
        transport = UrllibHttpTransport()
        cache = SQLiteResponseCache(store.path)
        provider_instances = {}
        if "arxiv" in providers:
            provider_instances["arxiv"] = ArxivProvider(transport, cache)
        if "semantic_scholar" in providers:
            provider_instances["semantic_scholar"] = SemanticScholarProvider(
                transport,
                cache,
                api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
            )
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
    unknown_providers = set(providers) - _DISCOVERY_PROVIDERS
    if unknown_providers:
        raise ValueError("stored discovery_providers contains an unknown provider")
    if enabled and not providers:
        raise ValueError("stored discovery_providers must be nonempty")

    max_results = config.get("discovery_max_results", 10)
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise TypeError("stored discovery_max_results must be an integer")
    if not 1 <= max_results <= 50:
        raise ValueError("stored discovery_max_results must be between 1 and 50")
    return enabled, providers, max_results


__all__ = ["build_engine", "load_resume_settings"]
