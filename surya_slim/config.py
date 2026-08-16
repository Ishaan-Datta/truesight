from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(ValueError):
    pass


_ENVIRONMENT_FIELDS = {
    "TRUESIGHT_API_URL": "api_url",
    "TRUESIGHT_HEALTH_URL": "health_url",
    "TRUESIGHT_MODEL": "model",
    "TRUESIGHT_API_KEY": "api_key",
    "TRUESIGHT_REQUEST_TIMEOUT_SECONDS": "request_timeout_seconds",
    "TRUESIGHT_HEALTH_TIMEOUT_SECONDS": "health_timeout_seconds",
    "TRUESIGHT_HEALTH_INTERVAL_SECONDS": "health_interval_seconds",
    "TRUESIGHT_RETRY_BACKOFF_SECONDS": "retry_backoff_seconds",
    "TRUESIGHT_MAX_TOKENS": "max_tokens",
    "TRUESIGHT_TEMPERATURE": "temperature",
    "TRUESIGHT_TOP_P": "top_p",
}

_FLOAT_FIELDS = {
    "request_timeout_seconds",
    "health_timeout_seconds",
    "health_interval_seconds",
    "retry_backoff_seconds",
    "temperature",
    "top_p",
}


def _environment_values(environ: Mapping[str, str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for environment_name, field_name in _ENVIRONMENT_FIELDS.items():
        if environment_name not in environ:
            continue
        value: object = environ[environment_name]
        try:
            if field_name in _FLOAT_FIELDS:
                value = float(value)
            elif field_name == "max_tokens":
                value = int(value)
        except ValueError as error:
            raise ConfigError(
                f"Invalid value for {environment_name}: {value!r}"
            ) from error
        values[field_name] = value
    return values


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    api_url: str
    health_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    request_timeout_seconds: float = 600.0
    health_timeout_seconds: float = 30.0
    health_interval_seconds: float = 1.0
    retry_backoff_seconds: float = 1.5
    max_tokens: int = 12288
    temperature: float = 0.0
    top_p: float = 0.1

    def __post_init__(self) -> None:
        if not isinstance(self.api_url, str) or not self.api_url.strip():
            raise ConfigError("api_url is required")

        api_url = self.api_url.rstrip("/")
        parsed_url = urlparse(api_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigError(f"api_url must be an HTTP(S) URL: {self.api_url!r}")
        object.__setattr__(self, "api_url", api_url)

        if self.health_url is not None:
            if not isinstance(self.health_url, str) or not self.health_url.strip():
                raise ConfigError("health_url cannot be empty")
            health_url = self.health_url.rstrip("/")
            parsed_health_url = urlparse(health_url)
            if (
                parsed_health_url.scheme not in {"http", "https"}
                or not parsed_health_url.netloc
            ):
                raise ConfigError(
                    f"health_url must be an HTTP(S) URL: {self.health_url!r}"
                )
            object.__setattr__(self, "health_url", health_url)

        if self.model is not None:
            if not isinstance(self.model, str) or not self.model.strip():
                raise ConfigError("model cannot be empty")
            object.__setattr__(self, "model", self.model.strip())

        positive_numbers = {
            "request_timeout_seconds": self.request_timeout_seconds,
            "health_timeout_seconds": self.health_timeout_seconds,
            "health_interval_seconds": self.health_interval_seconds,
        }
        for name, value in positive_numbers.items():
            if not isinstance(value, (int, float)) or value <= 0:
                raise ConfigError(f"{name} must be greater than zero")
        if not isinstance(self.retry_backoff_seconds, (int, float)):
            raise ConfigError("retry_backoff_seconds must be numeric")
        if self.retry_backoff_seconds < 0:
            raise ConfigError("retry_backoff_seconds cannot be negative")
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            raise ConfigError("max_tokens must be an integer")
        if self.max_tokens <= 0:
            raise ConfigError("max_tokens must be greater than zero")
        if not isinstance(self.temperature, (int, float)) or self.temperature < 0:
            raise ConfigError("temperature must be zero or greater")
        if not isinstance(self.top_p, (int, float)) or not 0 < self.top_p <= 1:
            raise ConfigError("top_p must be greater than zero and at most one")

    @property
    def resolved_health_url(self) -> str:
        if self.health_url is not None:
            return self.health_url
        server_url = self.api_url.removesuffix("/v1")
        return f"{server_url.rstrip('/')}/health"

    @classmethod
    def from_toml(
        cls,
        path: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> EndpointConfig:
        config_path = Path(path)
        with config_path.open("rb") as config_file:
            document = tomllib.load(config_file)

        endpoint_values = document.get("endpoint_config")
        if not isinstance(endpoint_values, dict):
            raise ConfigError(f"{config_path} must contain an [endpoint_config] table")

        allowed_fields = {field.name for field in fields(cls)}
        unknown_fields = set(endpoint_values) - allowed_fields
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ConfigError(f"Unknown [endpoint_config] setting(s): {names}")

        values = _environment_values(os.environ if environ is None else environ)
        values.update(endpoint_values)
        if "api_url" not in values:
            raise ConfigError(
                "api_url must be set in [endpoint_config] or TRUESIGHT_API_URL"
            )
        return cls(**values)

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> EndpointConfig:
        values = _environment_values(os.environ if environ is None else environ)
        if "api_url" not in values:
            raise ConfigError("TRUESIGHT_API_URL is required")
        return cls(**values)
