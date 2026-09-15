"""Additive collaboration tools; existing handoff contracts stay unchanged."""

PROJECT = {"type": "string", "minLength": 1, "maxLength": 128}
IDENTITY = {"type": "string", "format": "uuid"}
CLASSIFICATION = {"enum": ["public", "internal", "confidential", "restricted"]}

COLLABORATION_TOOLS = [
    {
        "name": "memory_handoff_inbox",
        "description": "Read a bounded live inbox: available (including expired leases), my active claims, or sent handoffs. No claim or automatic resume.",
        "inputSchema": {
            "type": "object", "required": ["project_id"], "additionalProperties": False,
            "properties": {
                "project_id": PROJECT, "unit_id": PROJECT,
                "view": {"enum": ["available", "claimed", "sent"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "cursor": {"type": "string", "minLength": 1, "maxLength": 2048},
                "max_classification": CLASSIFICATION,
            },
        },
    },
    {
        "name": "memory_handoff_status",
        "description": "Read project handoff delivery metadata without consuming it; acknowledgement is not task completion.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id"], "additionalProperties": False,
            "properties": {"project_id": PROJECT, "handoff_id": IDENTITY, "max_classification": CLASSIFICATION},
        },
    },
    {
        "name": "memory_handoff_renew",
        "description": "Extend an active owned lease to an absolute deadline. Retry the same deadline; never revives an expired lease or extends retention.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["project_id", "handoff_id", "claim_token", "claim_generation", "lease_expires_at"],
            "properties": {
                "project_id": PROJECT, "handoff_id": IDENTITY,
                "claim_token": {"type": "string", "minLength": 32, "maxLength": 256, "pattern": "^[A-Za-z0-9_-]+$"},
                "claim_generation": {"type": "integer", "minimum": 1},
                "lease_expires_at": {"type": "string", "format": "date-time", "maxLength": 40},
            },
        },
    },
]

COLLABORATION_SCOPES = {
    "memory_handoff_inbox": "read",
    "memory_handoff_status": "read",
    "memory_handoff_renew": "write",
}
