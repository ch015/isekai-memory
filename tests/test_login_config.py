"""Public desktop discovery cannot expose secrets or bypass authenticated APIs."""
from uuid import uuid4

import httpx

from isekai_memory.config import Settings
from isekai_memory.server.http_handler import create_app


async def test_discovery_uses_enabled_provider_config_and_preserves_authentication():
    tenant, client_id, audience = (str(uuid4()) for _ in range(3))
    settings = Settings(
        entra={"enabled": True, "tenant_id": tenant, "client_id": client_id, "audience": audience},
        github={"enabled": True, "client_id": "fixture-app", "client_secret": "never-publish-this", "allowed_user_ids": ["42"]},
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, None)), base_url="http://test") as client:
        response = await client.get("/auth/config")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"schema_version": 1, "providers": {
            "github": {"organization_id": "DevSecOps"},
            "entra": {"organization_id": "DevSecOps", "tenant_id": tenant, "client_id": client_id, "scope": f"api://{audience}/Memory.Access"},
        }}
        assert "never-publish-this" not in response.text
        assert "allowed_user_ids" not in response.text
        assert (await client.get("/auth/me")).status_code == 401
        assert (await client.post("/auth/config")).status_code == 401
        assert (await client.get("/auth/config", headers={"Origin": "https://other.example"})).status_code == 400


async def test_disabled_providers_are_not_advertised():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(), None)), base_url="http://test") as client:
        assert (await client.get("/auth/config")).json() == {"schema_version": 1, "providers": {}}
