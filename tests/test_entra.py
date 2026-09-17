"""Locally signed fixtures exercise API-token validation without an Entra tenant."""

import json
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from isekai_memory.config import Settings
from isekai_memory.projects import service
from isekai_memory.server.auth import Principal
from isekai_memory.server.entra import EntraVerifier
from isekai_memory.server.entra_config import EntraSettings
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.http_handler import create_app

TENANT, API, CLIENT, OBJECT = [str(uuid4()) for _ in range(4)]
CONFIG = dict(enabled=True, tenant_id=TENANT, audience=API, client_id=CLIENT)


@pytest.fixture
def signed():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())), "kid": "one", "use": "sig"}
    calls = []

    async def resolve(tenant, oid, org):
        calls.append((tenant, oid, org))
        return f"entra:{tenant}:{oid}"

    verifier = EntraVerifier(EntraSettings(**CONFIG), fetcher=lambda _: {"keys": [jwk]}, resolver=resolve)
    claims = dict(
        iss=f"https://login.microsoftonline.com/{TENANT}/v2.0",
        aud=API,
        tid=TENANT,
        oid=OBJECT,
        azp=CLIENT,
        ver="2.0",
        scp="Memory.Access",
        roles=["ADE.User"],
        exp=int(time.time()) + 600,
        nbf=int(time.time()) - 10,
        iat=int(time.time()) - 10,
    )

    def token(changes=None, missing=None, kid="one"):
        value = {**claims, **(changes or {})}
        if missing:
            value.pop(missing, None)
        return jwt.encode(value, private, algorithm="RS256", headers={"kid": kid})

    return verifier, token, calls


async def test_valid_identity_is_stable_and_no_global_admin(signed):
    verifier, token, calls = signed
    a = await verifier.verify(token({"preferred_username": "old@example.com"}))
    b = await verifier.verify(token({"preferred_username": "new@example.com"}))
    assert a == b
    assert a.provider == "entra" and a.organization_id == "DevSecOps"
    assert a.project_id is None and "admin" not in a.scopes
    assert calls == [(TENANT, OBJECT, "DevSecOps")] * 2


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.example"},
        {"aud": CLIENT},
        {"aud": "https://graph.microsoft.com"},
        {"tid": str(uuid4())},
        {"azp": str(uuid4())},
        {"oid": "email@example.com"},
        {"oid": 17},
        {"ver": "1.0"},
        {"exp": 1},
        {"nbf": 9999999999},
        {"iat": 9999999999},
        {"scp": "Other.Scope"},
        {"roles": []},
        {"roles": "ADE.User"},
        {"scp": ["Memory.Access"]},
    ],
)
async def test_wrong_binding_or_permission_never_resolves_user(signed, change):
    verifier, token, calls = signed
    with pytest.raises(MemoryToolError):
        await verifier.verify(token(change))
    assert not calls


@pytest.mark.parametrize("missing", ["exp", "iat", "nbf", "iss", "aud", "tid", "oid", "azp", "scp", "ver"])
async def test_required_claims_fail_closed(signed, missing):
    verifier, token, calls = signed
    with pytest.raises(MemoryToolError):
        await verifier.verify(token(missing=missing))
    assert not calls


async def test_wrong_signature_algorithm_and_unknown_key(signed):
    verifier, token, calls = signed
    for raw in (
        jwt.encode({"oid": OBJECT}, "x" * 40, algorithm="HS256", headers={"kid": "one"}),
        token(kid="missing"),
        "not-a-token",
    ):
        with pytest.raises(MemoryToolError):
            await verifier.verify(raw)
    assert not calls
    assert (await verifier.verify(token())).provider == "entra"


def test_config_rejects_insecure_or_ambiguous_issuer():
    for config in ({**CONFIG, "tenant_id": "common"}, {**CONFIG, "audience": "https://graph.microsoft.com"}):
        with pytest.raises(ValidationError):
            EntraSettings(**config)
    with pytest.raises(ValidationError):
        Settings(auth_enabled=False, entra=CONFIG)


async def test_project_role_and_organization_are_checked(monkeypatch):
    principal = Principal(
        "user", None, frozenset({"read", "write", "projects"}), provider="entra", organization_id="DevSecOps"
    )

    async def member(*_):
        return {"organization_id": "DevSecOps"}, "read"

    monkeypatch.setattr(service, "access", member)
    bound = await service.bind(principal, "memory_handoff_list", {"project_id": "p"})
    assert bound.scopes == frozenset({"read", "projects"})
    with pytest.raises(MemoryToolError):
        await service.bind(principal, "memory_project_register", {"project_id": "p", "organization_id": "other"})


async def test_http_identity_and_legacy_coexistence(signed, monkeypatch):
    verifier, token, _ = signed
    monkeypatch.setattr("isekai_memory.server.entra.EntraVerifier", lambda _: verifier)

    async def legacy(raw):
        assert raw == "legacy-fixture"
        return Principal("old-user", "p", frozenset({"read"}))

    monkeypatch.setattr("isekai_memory.server.http_handler.verify_token", legacy)
    app = create_app(Settings(entra=CONFIG), None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token()}"})
        assert response.status_code == 200 and response.json()["provider"] == "entra"
        assert response.headers["cache-control"] == "no-store"
        assert "access_token" not in response.text
        assert (await client.get("/auth/me", headers={"Authorization": "Bearer legacy-fixture"})).json()[
            "provider"
        ] == "token"
    app = create_app(Settings(entra={**CONFIG, "allow_legacy_tokens": False}), None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/auth/me", headers={"Authorization": "Bearer legacy-fixture"})).status_code == 401
