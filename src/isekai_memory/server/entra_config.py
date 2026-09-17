"""Single-tenant API configuration. No client secrets or untrusted discovery URLs."""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EntraSettings(BaseModel):
    enabled: bool = False
    allow_legacy_tokens: bool = True
    tenant_id: str = ""
    audience: str = ""
    client_id: str = ""
    scope: str = "Memory.Access"
    required_role: str = "ADE.User"
    organization_id: str = "DevSecOps"
    clock_skew_seconds: int = Field(default=30, ge=0, le=120)

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled:
            self.tenant_id = str(UUID(self.tenant_id))
            self.client_id = str(UUID(self.client_id))
            # v2 custom API access tokens use the resource application GUID as audience.
            self.audience = str(UUID(self.audience))
            if any(
                not value or len(value) > 128 or any(c.isspace() for c in value)
                for value in (self.scope, self.required_role, self.organization_id)
            ):
                raise ValueError("Entra scope, role and organization must be explicit identifiers")
        return self
