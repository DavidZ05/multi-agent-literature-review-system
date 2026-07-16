from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from src.literature_review.api import OpenAIChatClient
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery import (
    AllProvidersFailedError,
    ApprovalService,
    DiscoveryService,
    QueryPlanner,
)
from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage, utc_now_iso
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
    ClaimVerificationHandler,
    DocumentAcquisitionHandler,
    DiscoveryHandler,
    DraftingHandler,
    EvidenceIndexingHandler,
    EvidenceReviewGateHandler,
    PersistentWorkflowEngine,
    PlanningHandler,
    ScreeningHandler,
)

def build_engine(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
    *,
    discovery_enabled: bool = False,
    full_text_enabled: bool = False,
    providers: tuple[str, ...] = ("arxiv", "semantic_scholar"),
    max_results: int = 10,
    query_texts: tuple[str, ...] = (),
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
    drafting_handler = DraftingHandler(
        runtime_config,
        api_client=api_client,
        agent_factory=agent_factory,
    )
    if full_text_enabled:
        drafting_handler.enable_claim_verification()
    handlers = {
        WorkflowStage.PLANNING: PlanningHandler(
            discovery_enabled=discovery_enabled,
            full_text_enabled=full_text_enabled,
        ),
        WorkflowStage.DRAFTING: drafting_handler,
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
            "full_text_enabled": full_text_enabled,
            "discovery_providers": list(providers),
            "discovery_max_results": max_results,
            "discovery_query_texts": list(query_texts),
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
                        query_texts=query_texts,
                    )
                ),
                WorkflowStage.SCREENING: ScreeningHandler(),
                WorkflowStage.AWAITING_CORPUS_APPROVAL: ApprovalGateHandler(
                    approval,
                    full_text_enabled=full_text_enabled,
                ),
            }
        )
    if full_text_enabled:
        handlers.update(
            {
                WorkflowStage.ACQUIRING_DOCUMENTS: DocumentAcquisitionHandler(),
                WorkflowStage.INDEXING_EVIDENCE: EvidenceIndexingHandler(),
                WorkflowStage.CLAIM_VERIFICATION: ClaimVerificationHandler(),
                WorkflowStage.AWAITING_EVIDENCE_REVIEW: EvidenceReviewGateHandler(),
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


def load_resume_query_texts(
    artifact_store: LocalArtifactStore,
    run_id: str,
) -> tuple[str, ...]:
    try:
        request = artifact_store.read_json(run_id, "inputs/research_request.json")
    except FileNotFoundError:
        return ()
    if not isinstance(request, dict):
        raise TypeError("stored research request must be an object")
    config = request.get("runtime_config", {})
    if not isinstance(config, dict):
        raise TypeError("stored runtime_config must be an object")
    values = config.get("discovery_query_texts", ())
    if (
        not isinstance(values, (list, tuple))
        or any(not isinstance(value, str) or not value.strip() for value in values)
    ):
        raise TypeError("stored discovery_query_texts must be a list of strings")
    return tuple(dict.fromkeys(value.strip() for value in values))


def load_resume_full_text(
    artifact_store: LocalArtifactStore,
    run_id: str,
) -> bool:
    try:
        request = artifact_store.read_json(run_id, "inputs/research_request.json")
    except FileNotFoundError:
        return False
    if not isinstance(request, dict):
        raise TypeError("stored research request must be an object")
    config = request.get("runtime_config", {})
    if not isinstance(config, dict):
        raise TypeError("stored runtime_config must be an object")
    enabled = config.get("full_text_enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("stored full_text_enabled must be a boolean")
    return enabled


def retry_discovery(
    store: SQLiteWorkflowStore,
    artifact_root: Path,
    run_id: str,
    *,
    providers: tuple[str, ...],
    max_results: int,
    query_texts: tuple[str, ...] = (),
    provider_registry: ProviderRegistry | None = None,
    environment: Mapping[str, str] | None = None,
) -> ResearchRun:
    environment = os.environ if environment is None else environment
    provider_registry = provider_registry or build_provider_registry()
    unknown = set(providers) - set(provider_registry.names())
    if unknown:
        raise ProviderPluginError(f"unknown provider: {sorted(unknown)[0]}")
    if not providers:
        raise ValueError("providers must be nonempty")
    if not 1 <= max_results <= 50:
        raise ValueError("max_results must be between 1 and 50")
    normalized_queries = tuple(
        dict.fromkeys(query.strip() for query in query_texts if query.strip())
    )

    previous = store.get_run(run_id)
    allowed = (
        previous.status == RunStatus.WAITING
        and previous.current_stage == WorkflowStage.AWAITING_CORPUS_APPROVAL
    ) or (
        previous.status == RunStatus.RETRY_WAIT
        and previous.current_stage == WorkflowStage.DISCOVERING
    )
    if not allowed:
        raise ValueError("discovery can only be retried from its review or retry gate")

    active = replace(
        previous,
        status=RunStatus.ACTIVE,
        current_stage=WorkflowStage.DISCOVERING,
        updated_at=utc_now_iso(),
    )
    if not store.compare_and_update_run(
        active,
        expected_status=previous.status,
        expected_stage=previous.current_stage,
    ):
        raise ValueError("run changed while discovery retry was starting")
    store.append_event(
        run_id,
        "discovery_retry_started",
        {
            "providers": list(providers),
            "query_texts": list(normalized_queries),
            "max_results": max_results,
            "return_status": previous.status.value,
            "return_stage": previous.current_stage.value,
        },
        WorkflowStage.DISCOVERING,
    )

    transport = UrllibHttpTransport()
    cache = SQLiteResponseCache(store.path)
    context = ProviderContext(transport, cache, environment)
    instances = {
        provider_id: provider_registry.create(provider_id, context)
        for provider_id in providers
    }
    service = DiscoveryService(
        QueryPlanner(max_results=max_results),
        instances,
        query_texts=normalized_queries,
    )
    artifact_store = LocalArtifactStore(artifact_root)
    try:
        outcome = service.run(
            active,
            artifact_store,
            store,
            cancellation_check=lambda: (
                store.get_run(run_id).status == RunStatus.CANCELLED
            ),
        )
    except AllProvidersFailedError:
        target = replace(
            previous,
            status=(
                RunStatus.WAITING
                if previous.current_stage == WorkflowStage.AWAITING_CORPUS_APPROVAL
                else RunStatus.RETRY_WAIT
            ),
            updated_at=utc_now_iso(),
        )
        store.compare_and_update_run(
            target,
            expected_status=RunStatus.ACTIVE,
            expected_stage=WorkflowStage.DISCOVERING,
        )
        store.append_event(
            run_id,
            "discovery_retry_wait",
            {"reason": "all literature providers failed"},
            target.current_stage,
        )
        return store.get_run(run_id)
    except Exception:
        store.fail_active_discovery_attempts(run_id)
        store.compare_and_update_run(
            replace(previous, updated_at=utc_now_iso()),
            expected_status=RunStatus.ACTIVE,
            expected_stage=WorkflowStage.DISCOVERING,
        )
        raise

    for relative_path, content in outcome.output_artifacts.items():
        if isinstance(content, str):
            artifact_store.write_text(run_id, relative_path, content)
        else:
            artifact_store.write_json(run_id, relative_path, content)
    current = store.get_run(run_id)
    if current.status == RunStatus.CANCELLED or outcome.cancelled:
        return current
    waiting = replace(
        current,
        status=RunStatus.WAITING,
        current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
        updated_at=utc_now_iso(),
    )
    if not store.compare_and_update_run(
        waiting,
        expected_status=RunStatus.ACTIVE,
        expected_stage=WorkflowStage.DISCOVERING,
    ):
        return store.get_run(run_id)
    store.append_event(
        run_id,
        "discovery_retry_completed",
        {"attempt_id": outcome.attempt.attempt_id},
        WorkflowStage.AWAITING_CORPUS_APPROVAL,
    )
    return waiting


__all__ = [
    "build_engine",
    "load_resume_query_texts",
    "load_resume_full_text",
    "load_resume_settings",
    "retry_discovery",
]
