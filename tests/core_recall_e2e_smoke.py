"""Real Core client → Memory HTTP → validated optional Context reference.

Invoked by run_local_e2e with MEMORY_CORE_PYTHON and MEMORY_CORE_SOURCE explicitly
pointing to the sibling Core checkout. Never changes a real Project configuration.
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.environ["MEMORY_CORE_SOURCE"])

from isekai.execution.context import ContextAssembler, ContextSection  # noqa: E402
from isekai.memory.client import MemoryMcpClient  # noqa: E402
from isekai.memory.config import MemoryConfig  # noqa: E402
from isekai.memory.recall import ExperienceRecall  # noqa: E402


def main():
    project = os.environ["MEMORY_TEST_PROJECT_ID"]
    config = MemoryConfig(
        endpoint=os.environ["MEMORY_BASE_URL"] + "/mcp",
        organization_id="test",
        credential_ref="test",
        experience_recall=True,
        experience_max_chars=4000,
    )
    admin = MemoryMcpClient(config, SimpleNamespace(resolve=lambda ref: os.environ["MEMORY_ADMIN_TOKEN"]))
    reader = MemoryMcpClient(config, SimpleNamespace(resolve=lambda ref: os.environ["MEMORY_READ_TOKEN"]))
    source = admin.call_tool("memory_experience_list", {"project_id": project, "status": "superseded"})["items"][0]
    memory = admin.call_tool(
        "memory_experience_propose",
        {
            "project_id": project,
            "source_handoff_id": source["source_handoff_id"],
            "idempotency_key": uuid4().hex,
            "kind": "lesson",
            "title": "Core reference recall",
            "content": "Core reference recall preserves citations and execution boundaries.",
        },
    )
    review = {"project_id": project, "memory_id": memory["memory_id"], "action": "approve", "expected_version": 1}
    admin.call_tool("memory_experience_review", review)
    adapter = ExperienceRecall(reader, config)
    args = {
        "project_id": project,
        "lock_snapshot_digest": source["source_lock_digest"],
        "max_classification": "internal",
    }
    refs = adapter.recall("Core reference recall", **args)
    assert len(refs) == 1 and refs[0]["citation"]["memory_id"] == memory["memory_id"]
    assert json.loads(refs[0]["content"])["usage"] == "reference_only"
    sections = [ContextSection("policy", "policy", "Required policy", required=True)]
    sections.extend(
        ContextSection(ref["id"], "knowledge", ref["content"], priority=35, classification=ref["classification"])
        for ref in refs
    )
    assert len(ContextAssembler(128000).assemble(sections).sections) == 2
    assert len(ContextAssembler(100).assemble(sections).sections) == 1
    assert adapter.recall("Core reference recall", **{**args, "project_id": project + "-other"}) == []
    admin.call_tool("memory_experience_review", {**review, "action": "archive", "expected_version": 2})
    assert adapter.recall("Core reference recall", **args) == []
    print(
        json.dumps(
            {
                "core_live_recall": True,
                "citation_validated": True,
                "optional_context_budget": True,
                "cross_project_denied": True,
                "retirement_not_cached": True,
            }
        )
    )


if __name__ == "__main__":
    main()
