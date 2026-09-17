"""Dedicated GitHub OAuth app. Secrets remain on the Memory server."""

import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def subject(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError("GitHub user ID must be an immutable positive numeric ID")
    return value


class GitHubSettings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    enabled: bool = False
    allow_legacy_tokens: bool = True
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    allowed_user_ids: list[str] = Field(default_factory=list, max_length=1000)
    organization_id: str = "DevSecOps"

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.client_id) or not self.client_secret.get_secret_value():
                raise ValueError("GitHub OAuth client ID and server-side secret are required")
            if not self.allowed_user_ids or self.organization_id != "DevSecOps":
                raise ValueError("Explicit GitHub user IDs and DevSecOps organization are required")
            self.allowed_user_ids = list(dict.fromkeys(subject(value) for value in self.allowed_user_ids))
        return self
