from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

__all__ = ["AgentAPISettings", "AgentRuntimeConfig"]


@dataclass(frozen=True)
class AgentAPISettings:
    """Resolved API settings for one agent."""

    agent_id: str
    backend: str = "deterministic"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60

    @property
    def api_enabled(self) -> bool:
        return (
            self.backend == "api"
            and bool(self.api_base_url)
            and bool(self.api_key)
            and bool(self.model)
        )

    @property
    def active_backend(self) -> str:
        if self.api_enabled:
            return "api"
        return "deterministic"

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "<configured>" if self.api_key else ""
        data["api_enabled"] = self.api_enabled
        data["active_backend"] = self.active_backend
        return data


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Shared runtime switch for deterministic agents and future API-backed agents."""

    backend: str = "deterministic"
    api_mode: str = "single"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60
    agent_overrides: dict[str, dict[str, Any]] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentRuntimeConfig":
        values = os.environ if env is None else env

        def float_value(name: str, default: float) -> float:
            try:
                return float(values.get(name, default))
            except (TypeError, ValueError):
                return default

        def int_value(name: str, default: int) -> int:
            try:
                return int(values.get(name, default))
            except (TypeError, ValueError):
                return default

        backend = values.get("AGENT_BACKEND", "deterministic").strip().lower()
        if backend not in {"deterministic", "api"}:
            backend = "deterministic"
        api_mode = values.get("AGENT_API_MODE", "single").strip().lower()
        if api_mode not in {"single", "multi"}:
            api_mode = "single"
        return cls(
            backend=backend,
            api_mode=api_mode,
            api_base_url=values.get("AGENT_API_BASE_URL", "").strip(),
            api_key=values.get("AGENT_API_KEY", "").strip(),
            model=values.get("AGENT_MODEL", "").strip(),
            temperature=float_value("AGENT_TEMPERATURE", 0.2),
            timeout_seconds=int_value("AGENT_TIMEOUT_SECONDS", 60),
            agent_overrides=cls._agent_overrides(values),
        )

    @classmethod
    def _agent_overrides(cls, values: Mapping[str, str]) -> dict[str, dict[str, Any]]:
        agent_ids = [
            "search",
            "writer",
            "reviewer",
            "domain_expert",
            "structure_mentor",
            "review_synthesizer",
            "polish",
            "final_verification",
            "evaluation_reflection",
        ]
        overrides: dict[str, dict[str, Any]] = {}
        for agent_id in agent_ids:
            prefix = f"{agent_id.upper()}_AGENT_"
            raw_values = {
                "api_base_url": values.get(f"{prefix}API_BASE_URL", "").strip(),
                "api_key": values.get(f"{prefix}API_KEY", "").strip(),
                "model": values.get(f"{prefix}MODEL", "").strip(),
                "temperature": values.get(f"{prefix}TEMPERATURE", "").strip(),
                "timeout_seconds": values.get(f"{prefix}TIMEOUT_SECONDS", "").strip(),
            }
            cleaned = {
                key: value
                for key, value in raw_values.items()
                if value != ""
            }
            if cleaned:
                overrides[agent_id] = cleaned
        return overrides

    @property
    def api_enabled(self) -> bool:
        return self.default_settings().api_enabled

    @property
    def active_backend(self) -> str:
        return self.default_settings().active_backend

    def default_settings(self) -> AgentAPISettings:
        return AgentAPISettings(
            agent_id="default",
            backend=self.backend,
            api_base_url=self.api_base_url,
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )

    def for_agent(self, agent_id: str) -> AgentAPISettings:
        default = self.default_settings()
        if self.api_mode != "multi":
            return AgentAPISettings(agent_id=agent_id, **{
                "backend": default.backend,
                "api_base_url": default.api_base_url,
                "api_key": default.api_key,
                "model": default.model,
                "temperature": default.temperature,
                "timeout_seconds": default.timeout_seconds,
            })

        overrides = (self.agent_overrides or {}).get(agent_id, {})
        return AgentAPISettings(
            agent_id=agent_id,
            backend=self.backend,
            api_base_url=overrides.get("api_base_url", self.api_base_url),
            api_key=overrides.get("api_key", self.api_key),
            model=overrides.get("model", self.model),
            temperature=self._coerce_float(
                overrides.get("temperature", self.temperature),
                self.temperature,
            ),
            timeout_seconds=self._coerce_int(
                overrides.get("timeout_seconds", self.timeout_seconds),
                self.timeout_seconds,
            ),
        )

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "<configured>" if self.api_key else ""
        data["api_enabled"] = self.api_enabled
        data["active_backend"] = self.active_backend
        data["agent_overrides"] = {
            agent_id: self._sanitized_agent_override(agent_id)
            for agent_id in sorted((self.agent_overrides or {}).keys())
        }
        data["agent_settings"] = {
            agent_id: self.for_agent(agent_id).public_dict()
            for agent_id in [
                "search",
                "writer",
                "reviewer",
                "domain_expert",
                "structure_mentor",
                "review_synthesizer",
                "polish",
                "final_verification",
                "evaluation_reflection",
            ]
        }
        return data

    def _sanitized_agent_override(self, agent_id: str) -> dict[str, Any]:
        override = dict((self.agent_overrides or {}).get(agent_id, {}))
        if override.get("api_key"):
            override["api_key"] = "<configured>"
        return override

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
