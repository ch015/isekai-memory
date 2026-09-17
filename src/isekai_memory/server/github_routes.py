"""Small public OAuth exchange surface; no browser CORS and no credential logging."""

import json

from fastapi import Request
from fastapi.responses import JSONResponse

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.github import denied

PUBLIC = {("GET", "/auth/github/config"), ("POST", "/auth/github/exchange"), ("POST", "/auth/github/refresh")}


def install(app, github):
    @app.api_route("/auth/github/{operation}", methods=["GET", "POST"])
    async def github_auth(operation: str, request: Request):
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        try:
            if (request.method, request.url.path) not in PUBLIC or request.headers.get("origin"):
                raise denied("Invalid GitHub exchange route", 400)
            if operation == "config":
                result = github.config()
            else:
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise denied("JSON body is required", 400)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 4096:
                        raise denied("GitHub exchange request is too large", 413)
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    raise denied("Invalid GitHub exchange body", 400) from None
                result = await github.exchange(payload, refresh=operation == "refresh")
            return JSONResponse(result, headers=headers)
        except MemoryToolError as error:
            return JSONResponse(
                {"error": {"error_code": "MEM-AUTH-GITHUB", "message": error.message}},
                status_code=error.http_status,
                headers=headers,
            )
