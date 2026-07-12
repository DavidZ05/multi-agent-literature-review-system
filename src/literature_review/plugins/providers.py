from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import re

from src.literature_review.plugins.entrypoints import (
    entry_point_source,
    select_entry_points,
)
from src.literature_review.providers import (
    ArxivProvider,
    HttpTransport,
    ResponseCache,
    SearchProvider,
    SemanticScholarProvider,
)


PROVIDER_ENTRY_POINT_GROUP = "literature_review.providers"
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProviderPluginError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderContext:
    transport: HttpTransport
    cache: ResponseCache
    environment: Mapping[str, str]


ProviderBuilder = Callable[[ProviderContext], SearchProvider]


@dataclass(frozen=True)
class ProviderRegistration:
    provider_id: str
    label: str
    builder: ProviderBuilder
    source: str
    default_enabled: bool


class ProviderRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(
        self,
        provider_id: str,
        builder: ProviderBuilder,
        *,
        label: str | None = None,
        source: str = "application",
        default_enabled: bool = False,
    ) -> None:
        normalized = _provider_id(provider_id)
        if not callable(builder):
            raise ProviderPluginError(f"provider {normalized} builder must be callable")
        if normalized in self._registrations:
            existing = self._registrations[normalized]
            raise ProviderPluginError(
                f"provider {normalized} is already registered by {existing.source}"
            )
        display_label = (label or normalized.replace("_", " ").title()).strip()
        if not display_label:
            raise ProviderPluginError(f"provider {normalized} label must be nonblank")
        self._registrations[normalized] = ProviderRegistration(
            normalized,
            display_label,
            builder,
            source,
            default_enabled,
        )

    def create(self, provider_id: str, context: ProviderContext) -> SearchProvider:
        normalized = _provider_id(provider_id)
        try:
            registration = self._registrations[normalized]
        except KeyError as exc:
            raise ProviderPluginError(f"unknown provider: {normalized}") from exc
        provider = registration.builder(context)
        if getattr(provider, "provider_id", None) != normalized:
            raise ProviderPluginError(
                f"provider {normalized} returned an object with a mismatched provider_id"
            )
        if not callable(getattr(provider, "search", None)):
            raise ProviderPluginError(f"provider {normalized} must define search()")
        if not callable(getattr(provider, "fetch_details", None)):
            raise ProviderPluginError(f"provider {normalized} must define fetch_details()")
        extension = getattr(provider, "artifact_extension", "json")
        if (
            not isinstance(extension, str)
            or not re.fullmatch(r"[a-z0-9]{1,10}", extension)
        ):
            raise ProviderPluginError(
                f"provider {normalized} has an invalid artifact_extension"
            )
        return provider

    def names(self) -> tuple[str, ...]:
        return tuple(self._registrations)

    def options(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": registration.provider_id,
                "label": registration.label,
                "source": registration.source,
                "default_enabled": registration.default_enabled,
            }
            for registration in self._registrations.values()
        )


def build_provider_registry(
    *,
    load_entry_points: bool = True,
    entry_points: Iterable[object] | None = None,
) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        "arxiv",
        lambda context: ArxivProvider(context.transport, context.cache),
        label="arXiv",
        source="builtin",
        default_enabled=True,
    )
    registry.register(
        "semantic_scholar",
        lambda context: SemanticScholarProvider(
            context.transport,
            context.cache,
            api_key=context.environment.get("SEMANTIC_SCHOLAR_API_KEY", ""),
        ),
        label="Semantic Scholar",
        source="builtin",
        default_enabled=True,
    )
    if load_entry_points:
        for entry_point in select_entry_points(
            PROVIDER_ENTRY_POINT_GROUP,
            entry_points,
        ):
            try:
                builder = entry_point.load()
                registry.register(
                    entry_point.name,
                    builder,
                    label=getattr(builder, "plugin_label", None),
                    source=entry_point_source(entry_point),
                )
            except ProviderPluginError:
                raise
            except Exception as exc:
                raise ProviderPluginError(
                    f"failed to load provider plugin {entry_point.name}"
                ) from exc
    return registry


def _provider_id(value: str) -> str:
    if not isinstance(value, str):
        raise ProviderPluginError("provider id must be a string")
    normalized = value.strip().lower()
    if not _PLUGIN_ID.fullmatch(normalized):
        raise ProviderPluginError(
            "provider id must start with a letter and contain only lowercase "
            "letters, digits, or underscores"
        )
    return normalized


__all__ = [
    "PROVIDER_ENTRY_POINT_GROUP",
    "ProviderBuilder",
    "ProviderContext",
    "ProviderPluginError",
    "ProviderRegistration",
    "ProviderRegistry",
    "build_provider_registry",
]
