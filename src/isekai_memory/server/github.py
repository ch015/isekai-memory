"""GitHub OAuth code exchange and app-bound bearer verification; never accepts PATs."""

import asyncio
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import deque
from urllib.parse import urlencode, urlsplit

from isekai_memory.server.auth import Principal
from isekai_memory.server.entra import NoRedirect
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import github_identities

PREFIX = "iskgh."
SCOPES = "read:user offline_access"


def denied(message="GitHub authentication is invalid or expired", status=401):
    return MemoryToolError(message, data={"error_code": "MEM-AUTH-GITHUB"}, http_status=status)


def request_json(url, data, headers):
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **headers}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Response limit")
        value = json.loads(raw)
        if not isinstance(value, dict) or "error" in value:
            raise denied()
        return value
    except urllib.error.HTTPError as error:
        raise denied(status=503 if error.code >= 500 or error.code == 429 else 401) from None
    except MemoryToolError:
        raise
    except Exception:
        raise denied("GitHub identity service is temporarily unavailable", 503) from None


class GitHubAuth:
    def __init__(self, settings, *, fetcher=request_json, resolver=github_identities.resolve):
        self.settings, self.fetcher, self.resolver = settings, fetcher, resolver
        self.cache = {}  # SHA-256(token) -> (deadline, nonsecret identity), never raw credentials
        self.attempts = deque()
        self.active = 0

    def config(self):
        if not self.settings.enabled:
            raise denied("GitHub login is not configured on this Memory server", 404)
        return {"client_id": self.settings.client_id, "scope": SCOPES, "organization_id": "DevSecOps"}

    async def remote(self, url, data, headers):
        now = time.monotonic()
        while self.attempts and self.attempts[0] < now - 60:
            self.attempts.popleft()
        if self.active >= 8 or len(self.attempts) >= 120:
            raise denied("GitHub login is busy; retry shortly", 429)
        self.attempts.append(now)
        self.active += 1
        try:
            return await asyncio.to_thread(self.fetcher, url, data, headers)
        finally:
            self.active -= 1

    async def identity(self, token):
        self.config()
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,512}", token):
            raise denied()
        key = hashlib.sha256(token.encode()).hexdigest()
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            identity = cached[1]
        else:
            cfg = self.settings
            basic = base64.b64encode(f"{cfg.client_id}:{cfg.client_secret.get_secret_value()}".encode()).decode()
            document = await self.remote(
                f"https://api.github.com/applications/{cfg.client_id}/token",
                json.dumps({"access_token": token}).encode(),
                {
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/json",
                    "User-Agent": "ISEKAI-Memory",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
            )
            user, app, scopes = document.get("user", {}), document.get("app", {}), document.get("scopes")
            if (
                not isinstance(app, dict)
                or app.get("client_id") != cfg.client_id
                or not isinstance(user, dict)
                or type(user.get("id")) is not int
                or user["id"] <= 0
                or user["id"] >= 10**20
                or user.get("type") != "User"
                or not isinstance(user.get("login"), str)
                or not 1 <= len(user["login"]) <= 128
                or not isinstance(scopes, list)
                or not all(isinstance(scope, str) for scope in scopes)
                or "read:user" not in scopes
                or not set(scopes) <= {"read:user", "offline_access"}
            ):
                raise denied()
            identity = {"subject": str(user["id"]), "username": user["login"]}
            if len(self.cache) >= 1024:
                self.cache.clear()
            self.cache[key] = (time.monotonic() + 60, identity)
        if not self.settings.permits(identity["subject"], identity["username"]):
            raise denied("This GitHub user is not assigned to DevSecOps", 403)
        # Check local disable/organization on every request, even for cached provider responses.
        user_id = await self.resolver(identity["subject"], self.settings.organization_id)
        return {**identity, "user_id": user_id, "provider": "github", "organization_id": self.settings.organization_id}

    async def verify(self, raw):
        if not isinstance(raw, str) or not raw.startswith(PREFIX):
            raise denied()
        identity = await self.identity(raw[len(PREFIX) :])
        return Principal(
            identity["user_id"],
            None,
            frozenset({"read", "write", "projects"}),
            provider="github",
            organization_id=identity["organization_id"],
        )

    async def exchange(self, payload, *, refresh=False):
        self.config()
        fields = {"refresh_token"} if refresh else {"code", "code_verifier", "redirect_uri"}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise denied("Invalid GitHub exchange request", 400)
        if refresh:
            if not isinstance(payload["refresh_token"], str) or not re.fullmatch(
                r"[A-Za-z0-9_]{1,512}", payload["refresh_token"]
            ):
                raise denied("Invalid GitHub refresh request", 400)
            params = {**payload, "grant_type": "refresh_token"}
        else:
            code, verifier, redirect = (payload[key] for key in ("code", "code_verifier", "redirect_uri"))
            if (
                not isinstance(code, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", code)
                or not isinstance(verifier, str)
                or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                or not isinstance(redirect, str)
                or not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}/github/callback", redirect)
            ):
                raise denied("Invalid GitHub callback or PKCE verifier", 400)
            try:
                if not 1 <= urlsplit(redirect).port <= 65535:
                    raise ValueError()
            except ValueError:
                raise denied("Invalid GitHub callback port", 400) from None
            params = payload
        cfg = self.settings
        document = await self.remote(
            "https://github.com/login/oauth/access_token",
            urlencode(
                {
                    **params,
                    "client_id": cfg.client_id,
                    "client_secret": cfg.client_secret.get_secret_value(),
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = document.get("access_token")
        if str(document.get("token_type", "")).lower() != "bearer":
            raise denied()
        identity = await self.identity(token)
        result = {"access_token": PREFIX + token, "identity": identity}
        refresh_token, expires = document.get("refresh_token"), document.get("expires_in")
        if refresh_token is not None:
            if not isinstance(refresh_token, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,512}", refresh_token):
                raise denied()
            result["refresh_token"] = refresh_token
        if expires is not None:
            if type(expires) is not int or not 60 <= expires <= 365 * 86400:
                raise denied()
            result["expires_in"] = expires
        return result
