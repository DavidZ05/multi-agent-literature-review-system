from __future__ import annotations

import os
from dataclasses import asdict, dataclass
import ipaddress
import math
from typing import Any, Mapping
from urllib.parse import urlsplit

__all__ = ["AgentConfigurationError", "AgentAPISettings", "AgentRuntimeConfig"]


class AgentConfigurationError(ValueError):
    """Raised when runtime environment settings are inconsistent."""


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
            if name not in values:
                return default
            try:
                return float(values[name])
            except (TypeError, ValueError):
                raise AgentConfigurationError(f"{name} must be a number")

        def int_value(name: str, default: int) -> int:
            if name not in values:
                return default
            try:
                return int(values[name])
            except (TypeError, ValueError):
                raise AgentConfigurationError(f"{name} must be an integer")

        backend = values.get("AGENT_BACKEND", "deterministic").strip().lower()
        if backend not in {"deterministic", "api"}:
            raise AgentConfigurationError(
                "AGENT_BACKEND must be either 'deterministic' or 'api'"
            )
        api_mode = values.get("AGENT_API_MODE", "single").strip().lower()
        if api_mode not in {"single", "multi"}:
            raise AgentConfigurationError(
                "AGENT_API_MODE must be either 'single' or 'multi'"
            )
        config = cls(
            backend=backend,
            api_mode=api_mode,
            api_base_url=values.get("AGENT_API_BASE_URL", "").strip(),
            api_key=values.get("AGENT_API_KEY", "").strip(),
            model=values.get("AGENT_MODEL", "").strip(),
            temperature=float_value("AGENT_TEMPERATURE", 0.2),
            timeout_seconds=int_value("AGENT_TIMEOUT_SECONDS", 60),
            agent_overrides=cls._agent_overrides(values),
        )
        config.validate()
        return config

    @classmethod
    def _agent_overrides(cls, values: Mapping[str, str]) -> dict[str, dict[str, Any]]:
        overrides: dict[str, dict[str, Any]] = {}
        for agent_id in cls._agent_ids():
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
                if "temperature" in cleaned:
                    try:
                        cleaned["temperature"] = float(cleaned["temperature"])
                    except (TypeError, ValueError) as exc:
                        raise AgentConfigurationError(
                            f"{prefix}TEMPERATURE must be a number"
                        ) from exc
                if "timeout_seconds" in cleaned:
                    try:
                        cleaned["timeout_seconds"] = int(
                            cleaned["timeout_seconds"]
                        )
                    except (TypeError, ValueError) as exc:
                        raise AgentConfigurationError(
                            f"{prefix}TIMEOUT_SECONDS must be an integer"
                        ) from exc
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

    def validate(self) -> None:
        self._validate_numeric_settings(
            "AGENT_TEMPERATURE",
            self.temperature,
            "AGENT_TIMEOUT_SECONDS",
            self.timeout_seconds,
        )
        api_field_names = self._configured_api_field_names()
        if self.backend != "api":
            if api_field_names:
                configured = ", ".join(sorted(api_field_names))
                raise AgentConfigurationError(
                    "API settings were provided without AGENT_BACKEND=api: "
                    f"{configured}"
                )
            return

        for agent_id in self._agent_ids():
            settings = self.for_agent(agent_id)
            prefix = f"{agent_id.upper()}_AGENT"
            self._validate_numeric_settings(
                f"{prefix}_TEMPERATURE",
                settings.temperature,
                f"{prefix}_TIMEOUT_SECONDS",
                settings.timeout_seconds,
            )
            missing = []
            if not settings.api_base_url:
                missing.append("AGENT_API_BASE_URL")
            if not settings.api_key:
                missing.append("AGENT_API_KEY")
            if not settings.model:
                missing.append("AGENT_MODEL")
            if missing:
                raise AgentConfigurationError(
                    f"API backend for {agent_id} is missing "
                    + ", ".join(missing)
                )
            self._validate_api_base_url(settings.api_base_url, agent_id)

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
            for agent_id in self._agent_ids()
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
            raise AgentConfigurationError(
                "agent temperature overrides must be numbers"
            )

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            raise AgentConfigurationError(
                "agent timeout overrides must be integers"
            )

    @staticmethod
    def _validate_numeric_settings(
        temperature_name: str,
        temperature: float,
        timeout_name: str,
        timeout_seconds: int,
    ) -> None:
        if not math.isfinite(float(temperature)) or not 0.0 <= temperature <= 2.0:
            raise AgentConfigurationError(
                f"{temperature_name} must be between 0.0 and 2.0"
            )
        if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 600:
            raise AgentConfigurationError(
                f"{timeout_name} must be between 1 and 600 seconds"
            )

    @staticmethod
    def _validate_api_base_url(value: str, agent_id: str) -> None:
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise AgentConfigurationError(
                f"API base URL for {agent_id} is invalid"
            ) from exc
        if (
            hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AgentConfigurationError(
                f"API base URL for {agent_id} is invalid"
            )
        loopback = hostname.lower() == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme.lower() == "https":
            return
        if parsed.scheme.lower() == "http" and loopback:
            return
        raise AgentConfigurationError(
            f"API base URL for {agent_id} must use HTTPS unless it is loopback"
        )

    def _configured_api_field_names(self) -> set[str]:
        names = set()
        if self.api_base_url:
            names.add("AGENT_API_BASE_URL")
        if self.api_key:
            names.add("AGENT_API_KEY")
        if self.model:
            names.add("AGENT_MODEL")
        for agent_id, override in (self.agent_overrides or {}).items():
            prefix = f"{agent_id.upper()}_AGENT_"
            for key, value in override.items():
                if value == "":
                    continue
                names.add(f"{prefix}{key.upper()}")
        return names

    @staticmethod
    def _agent_ids() -> tuple[str, ...]:
        return (
            "search",
            "writer",
            "reviewer",
            "domain_expert",
            "structure_mentor",
            "review_synthesizer",
            "polish",
            "final_verification",
            "evaluation_reflection",
        )
