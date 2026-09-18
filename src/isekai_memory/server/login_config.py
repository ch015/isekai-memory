"""Public ADE login configuration, derived from the API's actual provider settings."""

from fastapi import Request
from fastapi.responses import JSONResponse


def install(app, settings):
    @app.get("/auth/config")
    async def login_config(request: Request):
        if request.headers.get("origin"):
            return JSONResponse({"error": "Desktop configuration only"}, status_code=400)
        providers = {}
        if settings.github.enabled:
            providers["github"] = {"organization_id": settings.github.organization_id}
        if settings.entra.enabled:
            entra = settings.entra
            providers["entra"] = {
                "organization_id": entra.organization_id,
                "tenant_id": entra.tenant_id,
                "client_id": entra.client_id,
                "scope": f"api://{entra.audience}/{entra.scope}",
            }
        return JSONResponse({"schema_version": 1, "providers": providers},
                            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
