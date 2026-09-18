"""GitHub OAuth fixtures: no external app, credentials or network required."""

import json
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from isekai_memory.config import Settings, _flatten_config
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.github import GitHubAuth
from isekai_memory.server.github_config import GitHubSettings
from isekai_memory.server.http_handler import create_app

CONFIG = dict(enabled=True, client_id="fixtureapp", client_secret="fixturesecret", allowed_user_ids=["42"])
PAYLOAD = dict(code="fixturecode", code_verifier="v" * 64, redirect_uri="http://127.0.0.1:49231/github/callback")


@pytest.fixture
def github():
    document = {
        "app": {"client_id": "fixtureapp"},
        "user": {"id": 42, "login": "alice", "type": "User"},
        "scopes": ["read:user"],
    }
    calls, resolved = [], []

    def fetch(url, data, headers):
        calls.append((url, data, headers))
        if url.endswith("/access_token"):
            return {
                "access_token": "gho_fixture",
                "token_type": "bearer",
                "expires_in": 28800,
                "refresh_token": "ghr_fixture",
            }
        return document

    async def resolve(identifier, org):
        resolved.append((identifier, org))
        return "github:" + identifier

    return GitHubAuth(GitHubSettings(**CONFIG), fetcher=fetch, resolver=resolve), document, calls, resolved


async def test_exchange_binds_app_pkce_and_identity_without_repo_scope(github):
    auth, _, calls, resolved = github
    result = await auth.exchange(PAYLOAD)
    assert result["access_token"] == "iskgh.gho_fixture"
    assert result["identity"]["user_id"] == "github:42"
    params = parse_qs(calls[0][1].decode())
    assert params["code_verifier"] == [PAYLOAD["code_verifier"]]
    assert params["client_secret"] == ["fixturesecret"]
    assert params["redirect_uri"] == [PAYLOAD["redirect_uri"]]
    assert calls[1][0] == "https://api.github.com/applications/fixtureapp/token"
    assert calls[1][2]["Authorization"].startswith("Basic ")
    assert resolved == [("42", "DevSecOps")]
    assert "secret" not in json.dumps(auth.config())
    assert set(auth.config()["scope"].split()) == {"read:user", "offline_access"}
    assert all("gho_fixture" not in key for key in auth.cache)


async def test_refresh_rotation_uses_server_secret_and_revalidates_user(github):
    auth, _, calls, _ = github
    result = await auth.exchange({"refresh_token": "ghr_fixture"}, refresh=True)
    assert result["refresh_token"] == "ghr_fixture"
    assert parse_qs(calls[0][1].decode())["grant_type"] == ["refresh_token"]
    assert (await auth.verify(result["access_token"])).scopes == frozenset({"read", "write", "projects"})


@pytest.mark.parametrize(
    "change",
    [
        {"app": {"client_id": "other"}},
        {"app": None},
        {"user": None},
        {"user": {"id": 42, "login": "alice", "type": "Bot"}},
        {"user": {"id": True, "login": "alice", "type": "User"}},
        {"user": {"id": "42", "login": "alice", "type": "User"}},
        {"user": {"id": 99, "login": "alice", "type": "User"}},
        {"scopes": ["read:user", "repo"]},
        {"scopes": ["user"]},
        {"scopes": "read:user"},
        {"scopes": [{}]},
    ],
)
async def test_untrusted_or_unassigned_identity_cannot_resolve(github, change):
    auth, document, _, resolved = github
    document.update(change)
    with pytest.raises(MemoryToolError):
        await auth.verify("iskgh.gho_fixture")
    assert not resolved


async def test_cached_identity_keeps_id_and_checks_local_disable_each_time(github):
    auth, document, calls, resolved = github
    first = await auth.verify("iskgh.gho_fixture")
    document["user"]["login"] = "renamed"
    second = await auth.verify("iskgh.gho_fixture")
    assert first == second and first.user_id == "github:42"
    assert len(calls) == 1 and len(resolved) == 2

    async def disabled(*_):
        raise MemoryToolError("Disabled", http_status=403)

    auth.resolver = disabled
    with pytest.raises(MemoryToolError):
        await auth.verify("iskgh.gho_fixture")
    auth.settings.allowed_user_ids = []
    with pytest.raises(MemoryToolError, match="not assigned"):
        await auth.verify("iskgh.gho_fixture")


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "redirect_uri": "https://attacker.example/github/callback"},
        {**PAYLOAD, "redirect_uri": "http://127.0.0.1:65536/github/callback"},
        {**PAYLOAD, "redirect_uri": "http://127.0.0.1:80/github/callback?next=evil"},
        {**PAYLOAD, "redirect_uri": "http://localhost:80/github/callback"},
        {**PAYLOAD, "code_verifier": "short"},
        {**PAYLOAD, "code": None},
        {**PAYLOAD, "client_id": "other"},
    ],
)
async def test_exchange_rejects_unbound_inputs_before_network(github, payload):
    auth, _, calls, _ = github
    with pytest.raises(MemoryToolError):
        await auth.exchange(payload)
    assert not calls


@pytest.mark.parametrize(
    "changes",
    [{"allowed_user_ids": []}, {"allowed_user_ids": ["alice@example.com"]}, {"client_secret": ""}, {"organization_id": "other"}],
)
def test_enabled_settings_fail_closed(changes):
    with pytest.raises(ValidationError):
        GitHubSettings(**{**CONFIG, **changes})


def test_settings_never_expose_secret_and_auth_cannot_be_disabled():
    settings = Settings(**_flatten_config({"auth": {"github": CONFIG}}))
    assert settings.github.enabled
    assert "fixturesecret" not in repr(settings)
    with pytest.raises(ValidationError) as error:
        Settings(auth_enabled=False, github=CONFIG)
    assert "fixturesecret" not in str(error.value)


@pytest.mark.parametrize("allowed", [["42"], ["alice"]])
async def test_http_public_exchange_and_bearer_do_not_fall_back_to_legacy(github, monkeypatch, allowed):
    auth, _, _, _ = github
    config = {**CONFIG, "allowed_user_ids": allowed, "allow_legacy_tokens": False}
    auth.settings = GitHubSettings(**config)
    monkeypatch.setattr("isekai_memory.server.github.GitHubAuth", lambda _: auth)
    app = create_app(Settings(github=config), None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/github/config")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert (await client.post("/auth/github/exchange", json=PAYLOAD)).status_code == 200
        assert (
            await client.post("/auth/github/exchange", json=PAYLOAD, headers={"Origin": "https://evil"})
        ).status_code == 400
        assert (
            await client.post("/auth/github/exchange", content="x" * 5000, headers={"Content-Type": "application/json"})
        ).status_code == 413
        assert (
            await client.post("/auth/github/exchange", content="{", headers={"Content-Type": "application/json"})
        ).status_code == 400
        assert (await client.post("/auth/github/unknown", json={})).status_code == 401
        assert (await client.get("/auth/me", headers={"Authorization": "Bearer legacy"})).status_code == 401
        response = await client.get("/auth/me", headers={"Authorization": "Bearer iskgh.gho_fixture"})
        assert response.json() == {"user_id": "github:42", "provider": "github", "organization_id": "DevSecOps"}
        assert "gho_fixture" not in response.text


async def test_disabled_provider_and_remote_limits_fail_closed(github):
    with pytest.raises(MemoryToolError):
        await GitHubAuth(GitHubSettings()).verify("iskgh.gho_fixture")
    auth, _, calls, _ = github
    auth.active = 8
    with pytest.raises(MemoryToolError) as error:
        await auth.verify("iskgh.gho_fixture")
    assert error.value.http_status == 429 and not calls


@pytest.mark.parametrize("entries", [["ALIce"], ["@Alice"], ["99", "alice"], ["42", "bob"]])
async def test_username_allowlist_preserves_numeric_identity_and_token_checks(github, entries):
    auth, document, calls, resolved = github
    auth.settings = GitHubSettings(**{**CONFIG, "allowed_user_ids": entries})
    result = await auth.exchange(PAYLOAD)
    assert result["identity"]["subject"] == "42"
    assert result["identity"]["user_id"] == "github:42"
    assert resolved == [("42", "DevSecOps")]
    assert len(calls) == 2  # Exchange and app-bound verification; no username lookup.
    assert (await auth.verify(result["access_token"])).user_id == "github:42"
    auth.cache.clear()
    document["app"]["client_id"] = "other-app"
    with pytest.raises(MemoryToolError):
        await auth.verify(result["access_token"])
    assert len(resolved) == 2


async def test_username_revocation_rename_and_local_disable(github):
    auth, document, _, resolved = github
    auth.settings = GitHubSettings(**{**CONFIG, "allowed_user_ids": ["alice"]})
    await auth.verify("iskgh.gho_fixture")
    auth.settings = GitHubSettings(**{**CONFIG, "allowed_user_ids": ["bob"]})
    with pytest.raises(MemoryToolError, match="not assigned"):
        await auth.verify("iskgh.gho_fixture")  # Recheck allowlist even while cached.
    assert len(resolved) == 1
    document["user"]["login"] = "bob"
    auth.cache.clear()
    assert (await auth.verify("iskgh.gho_fixture")).user_id == "github:42"

    async def disabled(*_):
        raise MemoryToolError("Disabled", http_status=403)

    auth.resolver = disabled
    with pytest.raises(MemoryToolError, match="Disabled"):
        await auth.verify("iskgh.gho_fixture")


async def test_numeric_username_does_not_match_a_different_users_numeric_id(github):
    auth, document, _, resolved = github
    document["user"].update(id=99, login="42")
    with pytest.raises(MemoryToolError, match="not assigned"):
        await auth.verify("iskgh.gho_fixture")
    assert not resolved
    auth.settings = GitHubSettings(**{**CONFIG, "allowed_user_ids": ["@42"]})
    assert (await auth.verify("iskgh.gho_fixture")).user_id == "github:99"
    assert resolved == [("99", "DevSecOps")]


@pytest.mark.parametrize("entry", ["", " ", "@", "a b", "a_b", "-alice", "alice-", "a--b", "a" * 40, "0", "01", "9" * 21, "https://github.com/alice", "álîce", 42])
def test_malformed_allowlist_entries_are_rejected(entry):
    with pytest.raises(ValidationError):
        GitHubSettings(**{**CONFIG, "allowed_user_ids": [entry]})


def test_env_accepts_usernames_mixed_with_existing_ids(monkeypatch):
    monkeypatch.setenv("ISEKAI_MEMORY_GITHUB__ENABLED", "true")
    monkeypatch.setenv("ISEKAI_MEMORY_GITHUB__CLIENT_ID", "fixtureapp")
    monkeypatch.setenv("ISEKAI_MEMORY_GITHUB__CLIENT_SECRET", "fixturesecret")
    monkeypatch.setenv("ISEKAI_MEMORY_GITHUB__ALLOWED_USER_IDS", '["ch015", "CH015", "@ch015", "42", "@123"]')
    settings = Settings()
    assert settings.github.allowed_user_ids == ["@ch015", "42", "@123"]
    assert settings.github.permits("99", "CH015")
    assert settings.github.permits("42", "renamed")
    assert not settings.github.permits("99", "42")
