"""Project catalog. Every row is actor-filtered; mutable records use revision guards."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

from fastapi.encoders import jsonable_encoder

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool

from .legacy import require_unclaimed_or_admin


def fail(message="Project is unavailable for this actor", code="MEM-PROJECT-0001", status=403):
    return MemoryToolError(message, data={"error_code": code}, http_status=status)


async def access(project_id, actor):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """SELECT p.*, m.role FROM memory_projects p
            LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=$2
            WHERE p.project_id=$1""",
            project_id,
            actor,
        )
    if row is None:
        return None, None
    return dict(row), "owner" if row["owner_id"] == actor else row["role"]


async def bind(principal, tool_name, arguments):
    """Only an explicitly issued 'projects' token can span assigned projects. Other token behavior is unchanged."""
    if principal.local or "projects" not in principal.scopes or tool_name == "memory_project_list":
        return principal
    project_id = arguments.get("project_id")
    if not isinstance(project_id, str):
        return principal
    row, role = await access(project_id, principal.user_id)
    if principal.provider in {"entra", "github"}:
        organization = row["organization_id"] if row else arguments.get("organization_id")
        if organization != principal.organization_id or (
            tool_name == "memory_project_register" and arguments.get("organization_id") != principal.organization_id
        ):
            raise fail("Project organization does not match this company account")
    if row is None and tool_name == "memory_project_register" and arguments.get("expected_revision") == 0:
        role = "owner"
    if role is None:
        raise fail()
    allowed = (
        {"read", "projects"}
        | ({"write"} if role in {"write", "owner"} else set())
        | ({"admin"} if role == "owner" else set())
    )
    # admin implies read/write only within the member's role, never across unassigned projects.
    scopes = set(principal.scopes)
    if "admin" in scopes:
        scopes.update({"read", "write"})
    if principal.provider in {"entra", "github"} and role == "owner":
        scopes.add("admin")  # project owner only; no global administrator scope
    return replace(principal, project_id=project_id, scopes=frozenset(scopes & allowed))


def validate_git(args):
    url = args.get("git_url")
    ref = args.get("git_ref")
    if url is None and ref is None:
        return
    if not isinstance(url, str) or not url or not isinstance(ref, str) or not ref:
        raise fail("Git URL and ref must be supplied together or both absent", "MEM-PROJECT-0002", 400)
    parsed = urlsplit(url)
    scp = re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+", url)
    if not scp and (
        parsed.scheme not in {"https", "ssh"}
        or not parsed.hostname
        or parsed.password
        or (parsed.scheme == "https" and parsed.username)
        or parsed.query
        or parsed.fragment
    ):
        raise fail("Git URL must be HTTPS or SSH without embedded secrets", "MEM-PROJECT-0002", 400)
    ref = args.get("git_ref")
    if (
        ref.startswith("-")
        or any(c.isspace() or ord(c) < 32 for c in ref)
        or any(s in ref for s in ("..", "@{", "\\", "~", "^", ":", "?", "*", "["))
    ):
        raise fail("Git ref is invalid", "MEM-PROJECT-0002", 400)


def validate_metadata(args):
    validate_git(args)
    setup = args["setup"]
    if set(setup) != {"schema_version", "config", "artifacts", "digest"} or setup["schema_version"] != 1:
        raise fail("Unsupported setup manifest", "MEM-PROJECT-0002", 400)
    config = setup.get("config")
    allowed = {
        "schema_version",
        "project_id",
        "project_root",
        "sources",
        "selection",
        "authority_scope",
        "agent_registry",
        "action_profiles",
        "stores",
        "context_profile",
        "execution_mode",
        "methodology_binding",
        "credential_refs",
    }
    if (
        not isinstance(config, dict)
        or config.keys() - allowed
        or config.get("project_id") != args["project_id"]
        or config.get("credential_refs") != []
    ):
        raise fail("Setup must bind this project and exclude credentials", "MEM-PROJECT-0002", 400)
    canonical = json.dumps(
        {k: v for k, v in setup.items() if k != "digest"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(canonical) > 512 * 1024 or setup["digest"] != "sha256:" + hashlib.sha256(canonical).hexdigest():
        raise fail("Setup digest/size is invalid", "MEM-PROJECT-0002", 400)


async def list_projects(args, principal):
    limit = args.get("limit", 50)
    scope = None if principal.local or "projects" in principal.scopes else principal.project_id
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.project_id,p.organization_id,p.name,p.git_url,p.git_ref,p.owner_id,p.revision,p.updated_at,
            CASE WHEN p.owner_id=$1 THEN 'owner' ELSE m.role END AS role
            FROM memory_projects p LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=$1
            WHERE (p.owner_id=$1 OR m.user_id IS NOT NULL) AND ($2::text IS NULL OR p.project_id=$2)
            AND ($5::text IS NULL OR p.organization_id=$5)
            AND p.project_id>$3 ORDER BY p.project_id LIMIT $4""",
            principal.user_id,
            scope,
            args.get("after", ""),
            limit + 1,
            principal.organization_id,
        )
    return jsonable_encoder(
        {
            "actor_id": principal.user_id,
            "items": [dict(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1]["project_id"] if len(rows) > limit else None,
        }
    )


async def get_project(args, principal):
    row, role = await access(args["project_id"], principal.user_id)
    if row is None or (role is None and not principal.local):
        raise fail()
    row["role"] = role or "local-admin"
    return jsonable_encoder(row)


async def register(args, principal):
    args = {"git_url": None, "git_ref": None, **args}
    validate_metadata(args)
    async with get_pool().acquire() as conn, conn.transaction():
        # Serialize create and update on the same project, including first registration.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", args["project_id"])
        row = await conn.fetchrow("SELECT * FROM memory_projects WHERE project_id=$1 FOR UPDATE", args["project_id"])
        if row and row["owner_id"] != principal.user_id and not principal.local:
            raise fail()
        if row is None:
            await require_unclaimed_or_admin(conn, principal, args["project_id"])
        fields = ("organization_id", "name", "git_url", "git_ref", "setup")
        if row and all(row[key] == args[key] for key in fields):
            return jsonable_encoder(dict(row))
        revision = row["revision"] if row else 0
        if revision != args["expected_revision"]:
            raise fail("Project changed; reload before publishing", "MEM-PROJECT-CONFLICT", 409)
        if row:
            row = await conn.fetchrow(
                """UPDATE memory_projects SET organization_id=$2,name=$3,git_url=$4,git_ref=$5,setup=$6,
                    revision=revision+1,updated_at=now() WHERE project_id=$1 RETURNING *""",
                args["project_id"],
                *(args[k] for k in fields),
            )
        else:
            row = await conn.fetchrow(
                """INSERT INTO memory_projects(project_id,organization_id,name,git_url,git_ref,setup,owner_id,revision)
                    VALUES($1,$2,$3,$4,$5,$6,$7,1) RETURNING *""",
                args["project_id"],
                *(args[k] for k in fields),
                principal.user_id,
            )
    return jsonable_encoder(dict(row))


async def assign(args, principal):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT * FROM memory_projects WHERE project_id=$1 FOR UPDATE", args["project_id"])
        if row is None or (row["owner_id"] != principal.user_id and not principal.local):
            raise fail()
        if args["user_id"] == row["owner_id"]:
            raise fail("Owner cannot be reassigned", "MEM-PROJECT-0002", 400)
        current = await conn.fetchval(
            "SELECT role FROM memory_project_members WHERE project_id=$1 AND user_id=$2",
            args["project_id"],
            args["user_id"],
        )
        desired = None if args["role"] == "remove" else args["role"]
        if current == desired:
            return {"project_id": args["project_id"], "revision": row["revision"], "changed": False}
        if row["revision"] != args["expected_revision"]:
            raise fail("Project changed; reload assignments", "MEM-PROJECT-CONFLICT", 409)
        if desired is None:
            await conn.execute(
                "DELETE FROM memory_project_members WHERE project_id=$1 AND user_id=$2",
                args["project_id"],
                args["user_id"],
            )
        else:
            await conn.execute(
                """INSERT INTO memory_project_members(project_id,user_id,role,assigned_by) VALUES($1,$2,$3,$4)
                ON CONFLICT(project_id,user_id) DO UPDATE SET role=EXCLUDED.role,assigned_by=EXCLUDED.assigned_by""",
                args["project_id"],
                args["user_id"],
                desired,
                principal.user_id,
            )
        revision = await conn.fetchval(
            "UPDATE memory_projects SET revision=revision+1,updated_at=now() WHERE project_id=$1 RETURNING revision",
            args["project_id"],
        )
    return {"project_id": args["project_id"], "revision": revision, "changed": True}


HANDLERS = {
    "memory_project_list": list_projects,
    "memory_project_get": get_project,
    "memory_project_register": register,
    "memory_project_assign": assign,
}
