"""Artifact policy management and Core-compatible semantic version resolution."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import total_ordering
from typing import Any

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import queries


@total_ordering
@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int = 0
    patch: int = 0
    prerelease: str | None = None
    build: str | None = field(default=None, compare=False)

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = re.fullmatch(
            r"v?(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:\.(0|[1-9]\d*))?"
            r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?",
            value,
        )
        if not match:
            raise ValueError(f"invalid semantic version: {value}")
        prerelease = match[4]
        if prerelease and any(item.isdigit() and len(item) > 1 and item.startswith("0") for item in prerelease.split(".")):
            raise ValueError(f"invalid semantic version: {value}")
        return cls(int(match[1]), int(match[2] or 0), int(match[3] or 0), prerelease, match[5])

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        own = (self.major, self.minor, self.patch)
        theirs = (other.major, other.minor, other.patch)
        if own != theirs:
            return own < theirs
        if self.prerelease is None:
            return False
        if other.prerelease is None:
            return True
        left = self.prerelease.split(".")
        right = other.prerelease.split(".")
        for own_item, other_item in zip(left, right, strict=False):
            if own_item == other_item:
                continue
            own_numeric = own_item.isdigit()
            other_numeric = other_item.isdigit()
            if own_numeric and other_numeric:
                return int(own_item) < int(other_item)
            if own_numeric != other_numeric:
                return own_numeric
            return own_item < other_item
        return len(left) < len(right)


def _conditions(expression: str) -> list[tuple[str, SemVer, str]]:
    if not expression.strip():
        raise ValueError("version range must not be empty")
    conditions: list[tuple[str, SemVer, str]] = []
    for condition in expression.split():
        match = re.fullmatch(r"(>=|<=|>|<|=|\^|~)(.+)", condition)
        if not match:
            raise ValueError(f"invalid version range: {expression}")
        operator, raw = match.groups()
        conditions.append((operator, SemVer.parse(raw), raw))
    return conditions


def validate_version_range(expression: str) -> None:
    _conditions(expression)


def version_satisfies(version: str, expression: str) -> bool:
    candidate = SemVer.parse(version)
    for operator, expected, raw in _conditions(expression):
        if operator == "^":
            upper = (
                SemVer(expected.major + 1)
                if expected.major > 0
                else SemVer(0, expected.minor + 1)
                if expected.minor > 0
                else SemVer(0, 0, expected.patch + 1)
            )
            matched = candidate >= expected and candidate < upper
        elif operator == "~":
            core = raw.split("-", 1)[0].split("+", 1)[0].removeprefix("v")
            upper = SemVer(expected.major + 1) if core.count(".") == 0 else SemVer(expected.major, expected.minor + 1)
            matched = candidate >= expected and candidate < upper
        else:
            matched = {
                ">=": candidate >= expected,
                "<=": candidate <= expected,
                ">": candidate > expected,
                "<": candidate < expected,
                "=": candidate == expected,
            }[operator]
        if not matched:
            return False
    return True


def match_project_pattern(project_id: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(project_id, pattern)


def resolve_policies(
    policies: list[dict[str, Any]],
    project_id: str,
    available_versions: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Resolve the highest-priority matching policy to the highest SemVer."""
    seen: set[tuple[str, str]] = set()
    resolved: list[dict[str, Any]] = []
    for policy in policies:
        if not match_project_pattern(project_id, policy["project_pattern"]):
            continue
        key = (policy["artifact_id"], policy["kind"])
        if key in seen:
            continue
        seen.add(key)
        if not policy["required"]:
            continue
        try:
            validate_version_range(policy["version_range"])
            candidates = sorted(
                available_versions.get(key, []),
                key=lambda candidate: SemVer.parse(candidate["version"]),
                reverse=True,
            )
        except ValueError as error:
            raise MemoryToolError(
                "artifact policy contains an invalid semantic version or range",
                data={"error_code": "MEM-POLICY-0002", "policy_id": str(policy["id"]), "cause": str(error)},
            ) from error
        selected = next(
            (candidate for candidate in candidates if version_satisfies(candidate["version"], policy["version_range"])),
            None,
        )
        if selected is not None:
            resolved.append(
                {
                    "artifact_id": selected["artifact_id"],
                    "kind": selected["kind"],
                    "version": selected["version"],
                    "manifest_digest": selected["manifest_digest"],
                    "artifact_digest": selected["artifact_digest"],
                    "archive_digest": selected["archive_digest"],
                }
            )
    return resolved


async def upsert_artifact_policy(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_version_range(arguments["version_range"])
    except ValueError as error:
        raise MemoryToolError(
            "invalid artifact policy version_range",
            data={"error_code": "MEM-POLICY-0002", "cause": str(error)},
        ) from error
    row = await queries.upsert_policy(
        organization_id=arguments["organization_id"],
        project_pattern=arguments["project_pattern"],
        kind=arguments["kind"],
        artifact_id=arguments["artifact_id"],
        version_range=arguments["version_range"],
        required=arguments.get("required", True),
        priority=arguments.get("priority", 0),
    )
    return {
        **{key: row[key] for key in ("organization_id", "project_pattern", "kind", "artifact_id", "version_range", "required", "priority")},
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def delete_artifact_policy(arguments: dict[str, Any]) -> dict[str, Any]:
    deleted = await queries.delete_policy(
        policy_id=arguments["policy_id"],
        organization_id=arguments["organization_id"],
    )
    if not deleted:
        raise MemoryToolError(
            "artifact policy not found",
            data={"error_code": "MEM-POLICY-0001", "policy_id": arguments["policy_id"]},
        )
    return {"policy_id": arguments["policy_id"], "deleted": True}
