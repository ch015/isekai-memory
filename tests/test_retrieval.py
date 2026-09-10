"""Provider, citation, configuration and ranking metric contracts."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from isekai_memory.config import Settings, load_settings
from isekai_memory.retrieval import service
from isekai_memory.retrieval.citations import BINDING_FIELDS, attach, canonical, digest
from isekai_memory.server.errors import MemoryToolError
from tests.retrieval_eval import metrics


def row():
    return {
        "id": uuid4(),
        "project_id": "p",
        "version": 2,
        "classification": "internal",
        "kind": "lesson",
        "title": "기억",
        "content": "응답 재시도 " * 100,
        "tags": ["receipt"],
        "source_handoff_id": uuid4(),
        "source_payload_digest": "sha256:" + "a" * 64,
        "source_lock_digest": "sha256:" + "b" * 64,
    }


def test_citation_binds_excerpt_full_content_and_source_identity():
    original = row()
    item = attach(original)
    citation = item["citation"]
    assert citation["excerpt_digest"] == digest(original["content"][:512])
    binding = {
        **{key: item[key] for key in BINDING_FIELDS},
        **{key: value for key, value in citation.items() if key != "binding_digest"},
    }
    assert digest(canonical(binding)) == citation["binding_digest"]
    changed = attach({**original, "content": original["content"] + "changed beyond excerpt"})
    assert changed["excerpt"] == item["excerpt"] and changed["citation"]["binding_digest"] != citation["binding_digest"]
    assert attach({**original, "project_id": "other"})["citation"]["binding_digest"] != citation["binding_digest"]
    assert "content" not in item and "tags" not in item


@pytest.mark.parametrize("exception", [TimeoutError(), OSError("do not expose details")])
async def test_retrieval_outages_are_explicit_and_redacted(monkeypatch, exception):
    async def fail(*args):
        raise exception

    monkeypatch.setattr(service, "fetch_rows", fail)
    with pytest.raises(MemoryToolError) as caught:
        await service.search({"project_id": "p", "query": "receipt"})
    assert caught.value.http_status == 503
    assert "do not expose" not in str(caught.value)


def test_provider_selection_is_validated_config_not_tool_input(tmp_path):
    assert Settings().retrieval_strategy == "postgres_lexical"
    with pytest.raises(ValidationError):
        Settings(retrieval_strategy="untrusted-plugin")
    config = tmp_path / "memory.json"
    config.write_text(json.dumps({"retrieval": {"strategy": "postgres_weighted_lexical"}}))
    assert load_settings(config).retrieval_strategy == "postgres_weighted_lexical"


def test_metrics_reward_order_and_do_not_inflate_duplicate_recall():
    first = metrics(["answer", "related"], {"answer": 3, "related": 1}, 3)
    reversed_order = metrics(["related", "answer"], {"answer": 3, "related": 1}, 3)
    assert first["recall_at_k"] == first["ndcg_at_k"] == first["mrr"] == 1
    assert reversed_order["ndcg_at_k"] < first["ndcg_at_k"]
    assert metrics(["answer", "answer"], {"answer": 3, "related": 1}, 3)["recall_at_k"] == 0.5
    assert metrics([], {}, 3)["empty_correct"]
