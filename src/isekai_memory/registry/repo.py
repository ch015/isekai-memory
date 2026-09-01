"""Repository registry — list and check updates for Git release repositories.

Repositories are configured via the server config file (``repos`` key).
Each entry tracks a Git repository URL, the artifact kind it provides,
and its artifact identity.  This module exposes MCP tools that let callers
discover registered repositories and check for newer releases.

Future: UI-based repository administration will replace direct config editing.
"""

from __future__ import annotations

import re
from typing import Any

from isekai_memory.config import Settings
from isekai_memory.server.errors import MemoryToolError

# Accepted repo entry schema enforced at query time.
_REPO_REQUIRED_KEYS = {"url", "kind", "artifact_id"}
_VALID_KINDS = {"foundation", "preset"}
_URL_PATTERN = re.compile(r"^https?://\S+$")


def _validate_repo_entry(entry: dict[str, Any], index: int) -> dict[str, Any]:
    """Validate a single repo config entry and return a normalized copy."""
    if not isinstance(entry, dict) or not set(entry) >= _REPO_REQUIRED_KEYS:
        raise MemoryToolError(
            f"Invalid repo entry at index {index}: required keys are {sorted(_REPO_REQUIRED_KEYS)}",
            data={"error_code": "MEM-REPO-0001"},
        )
    url = entry["url"]
    kind = entry["kind"]
    artifact_id = entry["artifact_id"]
    if not isinstance(url, str) or not _URL_PATTERN.match(url):
        raise MemoryToolError(
            f"Invalid repo URL at index {index}",
            data={"error_code": "MEM-REPO-0001"},
        )
    if kind not in _VALID_KINDS:
        raise MemoryToolError(
            f"Invalid repo kind at index {index}: must be one of {sorted(_VALID_KINDS)}",
            data={"error_code": "MEM-REPO-0001"},
        )
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise MemoryToolError(
            f"Invalid repo artifact_id at index {index}",
            data={"error_code": "MEM-REPO-0001"},
        )
    return {
        "url": url.strip(),
        "kind": kind,
        "artifact_id": artifact_id.strip(),
        "current_version": entry.get("current_version"),
    }


def _load_repos(settings: Settings, *, kind_filter: str | None = None) -> list[dict[str, Any]]:
    """Load and validate repo entries from settings, optionally filtering by kind."""
    repos = []
    for index, entry in enumerate(settings.repos):
        validated = _validate_repo_entry(entry, index)
        if kind_filter and validated["kind"] != kind_filter:
            continue
        repos.append(validated)
    return repos


async def list_repos(
    arguments: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """MCP tool: memory_repo_list — list registered artifact repositories."""
    settings = settings or Settings()
    kind_filter = arguments.get("kind")
    repos = _load_repos(settings, kind_filter=kind_filter)
    return [
        {
            "url": repo["url"],
            "kind": repo["kind"],
            "artifact_id": repo["artifact_id"],
            "current_version": repo.get("current_version"),
        }
        for repo in repos
    ]


async def check_repo_updates(
    arguments: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """MCP tool: memory_repo_check_updates — check for newer releases.

    This is a local metadata check against the configured ``current_version``.
    Actual Git/GitHub API integration for automatic release polling is a
    future enhancement.  For now, the tool returns the configured repo state
    so the user can compare against their installed versions.

    When ``repo_url`` is provided, only that repository is checked.
    """
    settings = settings or Settings()
    kind_filter = arguments.get("kind")
    repo_url = arguments.get("repo_url")
    repos = _load_repos(settings, kind_filter=kind_filter)

    if repo_url:
        repos = [r for r in repos if r["url"] == repo_url]

    results = []
    for repo in repos:
        results.append({
            "url": repo["url"],
            "kind": repo["kind"],
            "artifact_id": repo["artifact_id"],
            "current_version": repo.get("current_version"),
            # Placeholder — future: poll Git provider API for latest release tag
            "latest_version": None,
            "update_available": None,
            "message": "Automatic release polling is not yet implemented. "
                       "Check the repository releases page manually or configure current_version.",
        })

    return results
