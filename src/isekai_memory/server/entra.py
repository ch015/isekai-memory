"""Validate delegated Entra API tokens, then resolve a durable local identity."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from uuid import UUID

import jwt

from isekai_memory.server.auth import Principal
from isekai_memory.server.entra_config import EntraSettings
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import identities


def denied(message="Company authentication is invalid or expired", *, status=401):
    return MemoryToolError(message, data={"error_code": "MEM-AUTH-ENTRA"}, http_status=status)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_keys(tenant: str) -> dict:
    url = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    with urllib.request.build_opener(NoRedirect).open(url, timeout=8) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Oversized identity key response")
    return json.loads(data)


class EntraVerifier:
    def __init__(self, settings: EntraSettings, *, fetcher=fetch_keys, resolver=identities.resolve):
        self.settings, self.fetcher, self.resolver = settings, fetcher, resolver
        self.keys: dict = {}
        self.loaded_at = 0.0
        self.last_attempt = float("-inf")
        self.lock = asyncio.Lock()

    async def key(self, kid):
        now = time.monotonic()
        if kid in self.keys and now - self.loaded_at < 3600:
            return self.keys[kid]
        async with self.lock:
            now = time.monotonic()
            if kid in self.keys and now - self.loaded_at < 3600:
                return self.keys[kid]
            if now - self.last_attempt < 30:
                raise denied("Company signing key is unavailable")
            self.last_attempt = now
            try:
                document = await asyncio.to_thread(self.fetcher, self.settings.tenant_id)
                values = document.get("keys")
                if not isinstance(values, list) or not 1 <= len(values) <= 64:
                    raise ValueError("Invalid identity keys")
                keys = {}
                for value in values:
                    if (
                        value.get("kty") == "RSA"
                        and value.get("use", "sig") == "sig"
                        and value.get("alg", "RS256") == "RS256"
                    ):
                        identifier = value.get("kid")
                        if not isinstance(identifier, str) or not identifier or identifier in keys:
                            raise ValueError("Invalid signing key identifier")
                        keys[identifier] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(value))
                self.keys, self.loaded_at = keys, now
            except Exception as error:
                raise denied("Company identity service is temporarily unavailable", status=503) from error
        if kid not in self.keys:
            raise denied()
        return self.keys[kid]

    async def verify(self, raw: str) -> Principal:
        cfg = self.settings
        if not cfg.enabled or not raw or len(raw) > 16384:
            raise denied()
        try:
            header = jwt.get_unverified_header(raw)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 128
            ):
                raise ValueError("Invalid signing algorithm")
            key = await self.key(header["kid"])
            claims = jwt.decode(
                raw,
                key,
                algorithms=["RS256"],
                audience=cfg.audience,
                issuer=f"https://login.microsoftonline.com/{cfg.tenant_id}/v2.0",
                leeway=cfg.clock_skew_seconds,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid", "azp", "scp", "ver"]},
            )
            if claims["ver"] != "2.0" or claims["tid"] != cfg.tenant_id or claims["azp"] != cfg.client_id:
                raise ValueError("Identity binding mismatch")
            if not isinstance(claims["oid"], str):
                raise ValueError("Invalid object identifier")
            oid = str(UUID(claims["oid"]))
            if not isinstance(claims["scp"], str) or cfg.scope not in claims["scp"].split():
                raise denied("Company API permission is missing", status=403)
            roles = claims.get("roles", [])
            if not isinstance(roles, list) or cfg.required_role not in roles:
                raise denied("DevSecOps application access is not assigned", status=403)
        except MemoryToolError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError) as error:
            raise denied() from error
        user_id = await self.resolver(cfg.tenant_id, oid, cfg.organization_id)
        return Principal(
            user_id=user_id,
            project_id=None,
            scopes=frozenset({"read", "write", "projects"}),
            provider="entra",
            organization_id=cfg.organization_id,
        )
