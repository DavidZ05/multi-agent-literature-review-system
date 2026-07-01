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
    config = request.get("runtime_config", {})
    enabled = bool(config.get("discovery_enabled", False))
    providers = tuple(config.get("discovery_providers", ("arxiv", "semantic_scholar")))
    max_results = int(config.get("discovery_max_results", 10))
    return enabled, providers, max_results


__all__ = ["build_engine", "load_resume_settings"]
