from __future__ import annotations

import pytest

from isekai_memory.registry.policy import SemVer, resolve_policies, version_satisfies
from isekai_memory.server.errors import MemoryToolError


def candidate(version: str) -> dict[str, str]:
    return {
        "artifact_id": "demo", "kind": "foundation", "version": version,
        "manifest_digest": "sha256:" + "1" * 64,
        "artifact_digest": "sha256:" + "2" * 64,
        "archive_digest": "sha256:" + "3" * 64,
    }


def test_semver_matches_core_range_rules() -> None:
    assert version_satisfies("1.5.0", ">=1 <2")
    assert version_satisfies("1.4.2", "^1.2.0")
    assert not version_satisfies("2.0.0", "^1.2.0")
    assert SemVer.parse("1.0.0-alpha") < SemVer.parse("1.0.0")


def test_resolve_chooses_semver_max_not_latest_row() -> None:
    policies = [{
        "id": "policy-1", "project_pattern": "*", "artifact_id": "demo",
        "kind": "foundation", "version_range": ">=1 <3", "required": True,
    }]
    result = resolve_policies(
        policies,
        "project-1",
        {("demo", "foundation"): [candidate("1.9.0"), candidate("2.0.0"), candidate("1.10.0")]},
    )
    assert result[0]["version"] == "2.0.0"


def test_invalid_policy_range_is_controlled() -> None:
    policies = [{
        "id": "policy-1", "project_pattern": "*", "artifact_id": "demo",
        "kind": "foundation", "version_range": "latest", "required": True,
    }]
    with pytest.raises(MemoryToolError) as raised:
        resolve_policies(policies, "project-1", {("demo", "foundation"): [candidate("1.0.0")]})
    assert raised.value.data["error_code"] == "MEM-POLICY-0002"
