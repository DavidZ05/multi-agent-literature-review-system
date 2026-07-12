from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.evaluation import EvaluationReflectionAgent
from src.literature_review.plugins.entrypoints import (
    entry_point_source,
    select_entry_points,
)
from src.literature_review.review import (
    DomainExpertAgent,
    FinalVerificationReviewer,
    ReviewerAgent,
    ReviewSynthesizerAgent,
    StructureMentorAgent,
)
from src.literature_review.search import SearchAgent
from src.literature_review.writing import PolishAgent, WriterAgent


AGENT_ENTRY_POINT_GROUP = "literature_review.agents"
PROTECTED_AGENT_ROLES = frozenset({"search", "reviewer", "final_verification"})
REPLACEABLE_AGENT_ROLES = frozenset(
    {
        "writer",
        "domain_expert",
        "structure_mentor",
        "review_synthesizer",
        "polish",
        "evaluation_reflection",
    }
)
AGENT_ROLES = PROTECTED_AGENT_ROLES | REPLACEABLE_AGENT_ROLES


class AgentPluginError(ValueError):
    pass


AgentBuilder = Callable[[AgentRuntimeConfig, Any | None], object]


class AgentFactory:
    def __init__(self) -> None:
        self._builders: dict[str, AgentBuilder] = {}
        self._sources: dict[str, str] = {}

    def register_builtin(self, role: str, builder: AgentBuilder) -> None:
        self._register(role, builder, source="builtin", replace=False)

    def register_plugin(
        self,
        role: str,
        builder: AgentBuilder,
        *,
        source: str = "application",
    ) -> None:
        normalized = _agent_role(role)
        if normalized in PROTECTED_AGENT_ROLES:
            raise AgentPluginError(
                f"agent role {normalized} is a protected citation-safety component"
            )
        if normalized in self._builders and self._sources[normalized] != "builtin":
            raise AgentPluginError(
                f"agent role {normalized} is already provided by "
                f"{self._sources[normalized]}"
            )
        self._register(normalized, builder, source=source, replace=True)

    def create(
        self,
        role: str,
        runtime_config: AgentRuntimeConfig,
        api_client: Any | None = None,
    ) -> object:
        normalized = _agent_role(role)
        try:
            builder = self._builders[normalized]
        except KeyError as exc:
            raise AgentPluginError(f"agent role {normalized} is not registered") from exc
        agent = builder(runtime_config, api_client)
        required_methods = {
            "search": ("run",),
            "writer": ("run",),
            "reviewer": ("review",),
            "domain_expert": ("review",),
            "structure_mentor": ("review",),
            "review_synthesizer": ("synthesize",),
            "polish": ("run",),
            "final_verification": ("review",),
            "evaluation_reflection": ("evaluate", "to_markdown"),
        }[normalized]
        missing = [
            method for method in required_methods
            if not callable(getattr(agent, method, None))
        ]
        if missing:
            raise AgentPluginError(
                f"agent plugin {normalized} is missing {', '.join(missing)}"
            )
        try:
            setattr(agent, "agent_id", normalized)
        except Exception as exc:
            raise AgentPluginError(
                f"agent plugin {normalized} must allow its agent_id to be assigned"
            ) from exc
        return agent

    def manifest(self) -> dict[str, dict[str, object]]:
        return {
            role: {
                "source": self._sources[role],
                "protected": role in PROTECTED_AGENT_ROLES,
            }
            for role in sorted(self._builders)
        }

    def _register(
        self,
        role: str,
        builder: AgentBuilder,
        *,
        source: str,
        replace: bool,
    ) -> None:
        normalized = _agent_role(role)
        if not callable(builder):
            raise AgentPluginError(f"agent role {normalized} builder must be callable")
        if normalized in self._builders and not replace:
            raise AgentPluginError(f"agent role {normalized} is already registered")
        self._builders[normalized] = builder
        self._sources[normalized] = source


def build_agent_factory(
    *,
    load_entry_points: bool = True,
    entry_points: Iterable[object] | None = None,
) -> AgentFactory:
    factory = AgentFactory()
    builtins = {
        "search": SearchAgent,
        "writer": WriterAgent,
        "reviewer": ReviewerAgent,
        "domain_expert": DomainExpertAgent,
        "structure_mentor": StructureMentorAgent,
        "review_synthesizer": ReviewSynthesizerAgent,
        "polish": PolishAgent,
        "final_verification": FinalVerificationReviewer,
        "evaluation_reflection": EvaluationReflectionAgent,
    }
    for role, agent_type in builtins.items():
        factory.register_builtin(
            role,
            lambda config, client, agent_type=agent_type: agent_type(
                config,
                api_client=client,
            ),
        )
    if load_entry_points:
        for entry_point in select_entry_points(AGENT_ENTRY_POINT_GROUP, entry_points):
            try:
                factory.register_plugin(
                    entry_point.name,
                    entry_point.load(),
                    source=entry_point_source(entry_point),
                )
            except AgentPluginError:
                raise
            except Exception as exc:
                raise AgentPluginError(
                    f"failed to load agent plugin {entry_point.name}"
                ) from exc
    return factory


def _agent_role(value: str) -> str:
    if not isinstance(value, str):
        raise AgentPluginError("agent role must be a string")
    normalized = value.strip().lower()
    if normalized not in AGENT_ROLES:
        raise AgentPluginError(f"unknown agent role: {normalized}")
    return normalized


__all__ = [
    "AGENT_ENTRY_POINT_GROUP",
    "AGENT_ROLES",
    "AgentBuilder",
    "AgentFactory",
    "AgentPluginError",
    "PROTECTED_AGENT_ROLES",
    "REPLACEABLE_AGENT_ROLES",
    "build_agent_factory",
]
