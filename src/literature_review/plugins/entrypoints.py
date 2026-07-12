from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata


def select_entry_points(
    group: str,
    supplied: Iterable[object] | None = None,
) -> tuple[object, ...]:
    if supplied is not None:
        return tuple(supplied)
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return tuple(discovered.select(group=group))
    return tuple(discovered.get(group, ()))  # pragma: no cover - Python < 3.10


def entry_point_source(entry_point: object) -> str:
    value = str(getattr(entry_point, "value", "unknown"))
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return f"entry_point:{value}"
    name = getattr(distribution, "name", None)
    version = getattr(distribution, "version", None)
    if not name or not version:
        return f"entry_point:{value}"
    return f"entry_point:{value}@{name}=={version}"


__all__ = ["entry_point_source", "select_entry_points"]
