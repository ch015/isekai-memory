"""Directory discovery is explicit; existing project-scoped tokens remain scoped."""

ID = {"type": "string", "pattern": "^[a-z][a-z0-9._-]{0,127}$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 128}


def tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


PROJECT_TOOLS = [
    tool(
        "memory_project_list",
        "List projects owned by or assigned to this authenticated actor. Project tokens remain limited to their project.",
        {"after": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        [],
    ),
    tool(
        "memory_project_get",
        "Get one accessible project's clone metadata and pinned setup manifest.",
        {"project_id": ID},
        ["project_id"],
    ),
    tool(
        "memory_project_register",
        "Register a project or replace its metadata with an exact revision guard. Does not create a Git repository.",
        {
            "project_id": ID,
            "organization_id": TEXT,
            "name": TEXT,
            "source_kind": {"enum": ["git", "directory", "unknown"]},
            "git_url": {"type": ["string", "null"], "minLength": 1, "maxLength": 2048},
            "git_ref": {"type": ["string", "null"], "minLength": 1, "maxLength": 200},
            "setup": {"type": "object"},
            "expected_revision": {"type": "integer", "minimum": 0},
        },
        ["project_id", "organization_id", "name", "setup", "expected_revision"],
    ),
    tool(
        "memory_project_assign",
        "Owner assigns or removes directory access. Token scopes still limit allowed work operations.",
        {
            "project_id": ID,
            "user_id": TEXT,
            "role": {"enum": ["read", "write", "remove"]},
            "expected_revision": {"type": "integer", "minimum": 1},
        },
        ["project_id", "user_id", "role", "expected_revision"],
    ),
]
PROJECT_SCOPES = {
    "memory_project_list": "read",
    "memory_project_get": "read",
    "memory_project_register": "write",
    "memory_project_assign": "write",
}
