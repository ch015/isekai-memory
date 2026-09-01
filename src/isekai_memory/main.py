"""Entry point for stdio/HTTP MCP serving and token administration."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from isekai_memory.config import ServerMode, Settings, load_settings
from isekai_memory.server.auth import Principal, authorize_tool, hash_token
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.mcp_handler import McpStdioServer
from isekai_memory.server.validation import validate_tool_arguments


class ToolDispatcher:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def __call__(self, tool_name: str, arguments: dict[str, Any], principal: Principal) -> Any:
        from isekai_memory.handoff.service import (
            acknowledge_claimed_handoff,
            claim_handoff_recoverable,
            get_claimed_handoff,
            list_handoffs,
            nack_claimed_handoff,
            pull_handoff,
            push_handoff,
        )
        from isekai_memory.registry.repo import check_repo_updates, list_repos

        validate_tool_arguments(tool_name, arguments)
        authorize_tool(principal, tool_name, arguments)

        # --- Repository Registry ----------------------------------------------
        if tool_name == "memory_repo_list":
            return await list_repos(arguments, settings=self.settings)
        if tool_name == "memory_repo_check_updates":
            return await check_repo_updates(arguments, settings=self.settings)

        # --- Work Handoff -----------------------------------------------------
        if tool_name == "memory_handoff_push":
            return await push_handoff(arguments, settings=self.settings, from_user=principal.user_id)
        if tool_name == "memory_handoff_pull":
            return await pull_handoff(
                arguments,
                claimed_by=principal.user_id,
                authorized_project_id=None if principal.local else principal.project_id,
            )
        recoverable_handlers = {
            "memory_handoff_claim": claim_handoff_recoverable,
            "memory_handoff_get_claimed": get_claimed_handoff,
            "memory_handoff_ack": acknowledge_claimed_handoff,
            "memory_handoff_nack": nack_claimed_handoff,
        }
        recoverable_handler = recoverable_handlers.get(tool_name)
        if recoverable_handler is not None:
            keyword_arguments: dict[str, Any] = {
                "claimed_by": principal.user_id,
                "authorized_project_id": None if principal.local else principal.project_id,
            }
            if tool_name == "memory_handoff_claim":
                keyword_arguments["settings"] = self.settings
            return await recoverable_handler(arguments, **keyword_arguments)
        simple_handlers = {
            "memory_handoff_list": list_handoffs,
        }
        handler = simple_handlers.get(tool_name)
        if handler is None:
            raise MemoryToolError(f"Tool '{tool_name}' is not recognized", code=-32602, data={"error_code": "MEM-TOOL-0001"})
        return await handler(arguments)


async def dispatch_tool(
    tool_name: str,
    arguments: dict[str, Any],
    principal: Principal | None = None,
    settings: Settings | None = None,
) -> Any:
    """Compatibility entry point used by tests and embedded callers."""
    return await ToolDispatcher(settings or Settings())(tool_name, arguments, principal or Principal.local_stdio())


async def run_stdio(settings: Settings) -> None:
    from isekai_memory.store.database import close_pool, init_pool

    await init_pool(settings)
    try:
        await McpStdioServer(ToolDispatcher(settings)).serve()
    finally:
        await close_pool()


def run_http(settings: Settings) -> None:
    import uvicorn

    from isekai_memory.server.http_handler import create_app

    uvicorn.run(create_app(settings, ToolDispatcher(settings)), host=settings.host, port=settings.port, log_level="info", access_log=True)


async def issue_token(settings: Settings, args: argparse.Namespace) -> None:
    from isekai_memory.store import queries
    from isekai_memory.store.database import close_pool, init_pool

    scopes = [item.strip() for item in args.scopes.split(",") if item.strip()]
    invalid = sorted(set(scopes) - {"read", "write", "admin"})
    if not scopes or invalid:
        raise SystemExit(f"Invalid scopes: {invalid or scopes}")
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=args.expires_hours) if args.expires_hours else None
    await init_pool(settings)
    try:
        row = await queries.create_token(
            token_hash=hash_token(raw_token), project_id=args.project_id, user_id=args.user_id,
            scopes=scopes, expires_at=expires_at,
        )
    finally:
        await close_pool()
    print(json.dumps({
        "token_id": str(row["id"]), "token": raw_token, "project_id": row["project_id"],
        "user_id": row["user_id"], "scopes": row["scopes"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
    }))


async def revoke_token(settings: Settings, token_id: str) -> None:
    from isekai_memory.store import queries
    from isekai_memory.store.database import close_pool, init_pool

    await init_pool(settings)
    try:
        revoked = await queries.revoke_token(token_id=token_id)
    finally:
        await close_pool()
    if not revoked:
        raise SystemExit("Token not found or already revoked")
    print(json.dumps({"token_id": token_id, "revoked": True}))


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="isekai-memory", description="ISEKAI Memory MCP Server")
    parser.add_argument("--mode", choices=["http", "stdio"], default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None)
    admin = parser.add_mutually_exclusive_group()
    admin.add_argument("--issue-token", action="store_true", help="Issue one project-scoped token and print it once")
    admin.add_argument("--revoke-token", metavar="TOKEN_ID", help="Revoke a token by UUID")
    parser.add_argument("--project-id")
    parser.add_argument("--user-id")
    parser.add_argument("--scopes", default="read,write")
    parser.add_argument("--expires-hours", type=int, default=None)
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    if args.issue_token:
        if not args.project_id or not args.user_id:
            parser.error("--issue-token requires --project-id and --user-id")
        asyncio.run(issue_token(settings, args))
        return
    if args.revoke_token:
        asyncio.run(revoke_token(settings, args.revoke_token))
        return
    if args.mode is not None:
        settings.mode = ServerMode(args.mode)
    if args.port is not None:
        settings.port = args.port
    if args.host is not None:
        settings.host = args.host
    if settings.mode == ServerMode.stdio:
        asyncio.run(run_stdio(settings))
    else:
        run_http(settings)


if __name__ == "__main__":
    cli()
