"""Server configuration — environment variables with optional JSON file override."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from isekai_memory.server.entra_config import EntraSettings
from isekai_memory.server.github_config import GitHubSettings


class ServerMode(StrEnum):
    http = "http"
    stdio = "stdio"


class Settings(BaseSettings):
    """Environment settings prefixed with ``ISEKAI_MEMORY_``.

    Values supplied by a JSON file are explicit overrides of environment values.
    """

    model_config = SettingsConfigDict(
        env_prefix="ISEKAI_MEMORY_",
        env_nested_delimiter="__",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    database_url: str = "postgresql://isekai:isekai@localhost:5432/isekai_memory"
    db_pool_min: int = Field(default=2, ge=1)
    db_pool_max: int = Field(default=10, ge=1)

    mode: ServerMode = ServerMode.http
    host: str = "0.0.0.0"
    port: int = Field(default=8100, ge=1, le=65535)

    max_archive_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_archive_uncompressed_bytes: int = Field(default=1024 * 1024 * 1024, ge=1)
    max_archive_members: int = Field(default=10_000, ge=1, le=100_000)
    max_http_request_bytes: int = Field(default=70 * 1024 * 1024, ge=1)

    auth_enabled: bool = True
    auth_token_header: str = "X-Isekai-Token"
    # Deprecated: stdio uses the local process boundary rather than a non-standard
    # initialize parameter. Kept temporarily so old config files still load.
    auth_static_token: str | None = None
    entra: EntraSettings = Field(default_factory=EntraSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)

    handoff_default_expiry_hours: int = Field(default=168, ge=1, le=8760)
    handoff_max_raw_output_bytes: int = Field(default=1024 * 1024, ge=0)
    handoff_claim_lease_min_seconds: int = Field(default=30, ge=1, le=86_400)
    handoff_claim_lease_default_seconds: int = Field(default=300, ge=1, le=86_400)
    handoff_claim_lease_max_seconds: int = Field(default=3600, ge=1, le=86_400)

    retrieval_strategy: Literal["postgres_lexical", "postgres_weighted_lexical"] = "postgres_lexical"

    generation_enabled: bool = False
    generation_max_input_chars: int = Field(default=8192, ge=256, le=16384)
    generation_max_output_chars: int = Field(default=4296, ge=256, le=4296)
    generation_timeout_seconds: int = Field(default=10, ge=1, le=30)
    generation_lease_seconds: int = Field(default=60, ge=10, le=300)

    # Repository registry — list of Git release repositories to track.
    # Each entry: {"url": "<repo-url>", "kind": "foundation"|"preset", "artifact_id": "<id>"}
    # Managed via config file; future UI administration planned.
    repos: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bounds(self) -> Settings:
        if self.github.enabled and not self.auth_enabled:
            raise ValueError("GitHub authentication requires auth_enabled=true")
        if self.entra.enabled and not self.auth_enabled:
            raise ValueError("Entra authentication requires auth_enabled=true")
        if self.generation_lease_seconds <= self.generation_timeout_seconds + 5:
            raise ValueError("generation lease must exceed timeout by more than five seconds")
        if self.db_pool_max < self.db_pool_min:
            raise ValueError("db_pool_max must be greater than or equal to db_pool_min")
        if self.max_archive_uncompressed_bytes < self.max_archive_bytes:
            raise ValueError("max_archive_uncompressed_bytes must be >= max_archive_bytes")
        if not (
            self.handoff_claim_lease_min_seconds
            <= self.handoff_claim_lease_default_seconds
            <= self.handoff_claim_lease_max_seconds
        ):
            raise ValueError("handoff claim lease bounds must satisfy min <= default <= max")
        return self


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from environment, optionally overridden by a JSON file."""
    if config_path is None:
        return Settings()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("Config file root must be a JSON object")
    return Settings(**_flatten_config(payload))


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "database_url": "database_url",
        "server.mode": "mode",
        "server.host": "host",
        "server.port": "port",
        "storage.max_archive_bytes": "max_archive_bytes",
        "storage.max_archive_uncompressed_bytes": "max_archive_uncompressed_bytes",
        "storage.max_archive_members": "max_archive_members",
        "server.max_http_request_bytes": "max_http_request_bytes",
        "auth.enabled": "auth_enabled",
        "auth.token_header": "auth_token_header",
        "auth.static_token": "auth_static_token",
        "handoff.default_expiry_hours": "handoff_default_expiry_hours",
        "handoff.max_raw_output_bytes": "handoff_max_raw_output_bytes",
        "handoff.claim_lease_min_seconds": "handoff_claim_lease_min_seconds",
        "handoff.claim_lease_default_seconds": "handoff_claim_lease_default_seconds",
        "handoff.claim_lease_max_seconds": "handoff_claim_lease_max_seconds",
        "db.pool_min": "db_pool_min",
        "db.pool_max": "db_pool_max",
        "repos": "repos",
        "retrieval.strategy": "retrieval_strategy",
        "generation.enabled": "generation_enabled",
        "generation.max_input_chars": "generation_max_input_chars",
        "generation.max_output_chars": "generation_max_output_chars",
        "generation.timeout_seconds": "generation_timeout_seconds",
        "generation.lease_seconds": "generation_lease_seconds",
    }
    flat = _flatten_dict(data)
    result = {setting_key: flat[json_key] for json_key, setting_key in mapping.items() if json_key in flat}
    if isinstance(data.get("auth"), dict) and "entra" in data["auth"]:
        result["entra"] = data["auth"]["entra"]
    if isinstance(data.get("auth"), dict) and "github" in data["auth"]:
        result["github"] = data["auth"]["github"]
    for key, value in data.items():
        if key in Settings.model_fields and key not in result:
            result[key] = value
    return result


def _flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    items: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, full_key))
        else:
            items[full_key] = value
    return items
