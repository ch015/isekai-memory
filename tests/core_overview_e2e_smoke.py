"""Read-only real Core -> Memory HTTP smoke, after the M8 continuity fixture."""

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.infrastructure.errors import IsekaiError  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from isekai.memory.overview import CollaborationClient  # noqa: E402


def main():
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(endpoint=os.environ["MEMORY_BASE_URL"] + "/mcp", organization_id="test", credential_ref="test")

    def raw(key):
        return MemoryMcpClient(config, SimpleNamespace(resolve=lambda _: os.environ[key]))

    admin_raw = raw("MEMORY_ADMIN_TOKEN")
    admin = CollaborationClient(admin_raw, project)
    reader = CollaborationClient(raw("MEMORY_READ_TOKEN"), project)
    overview = admin.overview(scope="project", include_acknowledged=True)
    assert overview["identity"]["project_admin"] and overview["continuity_policy"]["configured"]
    assert overview["counts"]["work"]["value"] == 2
    assert overview["counts"]["inbox"]["value"] == 2
    assert all(item["value"] is None for item in overview["telemetry"].values())
    work = admin.listing("work", scope="project")
    assert len(work["items"]) == 2
    assert all(item["state"] == "completed" and item["execution_state"] == "unobserved" for item in work["items"])
    bundle = work["items"][0]["bundle_id"]
    before = admin_raw.call_tool("memory_continuity_status", {"project_id": project, "bundle_id": bundle})
    for view in ("work", "inbox", "sent", "checkpoints"):
        result = admin.listing(view, scope="project", include_acknowledged=True, limit=1)
        assert len(result["items"]) == 1
        if result["has_more"]:
            later = admin.listing(view, scope="project", include_acknowledged=True, limit=1, cursor=result["next_cursor"])
            assert later["items"][0]["id"] != result["items"][0]["id"]
    personal = reader.overview(include_acknowledged=True)
    assert not personal["identity"]["project_admin"]
    assert personal["counts"]["checkpoints"]["value"] == 0
    assert personal["counts"]["inbox"]["value"] == 1
    try:
        reader.overview(scope="project")
        raise AssertionError("non-admin project scope was accepted")
    except IsekaiError as error:
        assert error.code == "ISK-MEMORY-0005"
    after = admin_raw.call_tool("memory_continuity_status", {"project_id": project, "bundle_id": bundle})
    for value in (before, after):
        value.pop("observed_at")
    assert before == after
    print(json.dumps({"core_collaboration_http": True, "project_scope_admin_only": True,
                      "metadata_pagination": True, "no_mutation": True, "telemetry_unavailable_not_zero": True}))


if __name__ == "__main__":
    main()
