"""Offline provider, configuration and public generation contracts."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from isekai_memory.config import Settings, load_settings
from isekai_memory.generation.contracts import ExtractionInput, GenerationFailure
from isekai_memory.generation.provider import StructuredExtractor
from isekai_memory.generation.worker import run
from isekai_memory.main import cli
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments


async def test_structured_extractor_is_an_attributed_quote_not_a_synthesized_procedure():
    source = ExtractionInput(summary="  결과 그대로 보존합니다.  ", objective="objective", result_status="failed")
    candidate = await StructuredExtractor().extract(source)
    assert candidate.kind == "fact"
    assert candidate.content == source.summary.strip()
    assert candidate.title == source.objective
    assert await StructuredExtractor().extract(replace(source, summary="  ")) is None


@pytest.mark.parametrize("text", ["api_key=secret-value", "Bearer credentials", "-----BEGIN PRIVATE KEY-----"])
async def test_obvious_sensitive_sources_are_not_automatically_copied(text):
    with pytest.raises(GenerationFailure, match="sensitive_source"):
        await StructuredExtractor().extract(ExtractionInput(text, "objective", "succeeded"))


async def test_worker_disabled_by_default_before_database_access():
    with pytest.raises(MemoryToolError, match="disabled"):
        await run(Settings(), project_id="project")
    with pytest.raises(SystemExit) as exc:
        cli(["--run-generation", "--project-id", "project"])
    assert exc.value.code == 2


def test_generation_settings_are_explicit_and_leases_exceed_processing_budget(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"generation":{"enabled":true,"max_input_chars":2048}}')
    settings = load_settings(path)
    assert settings.generation_enabled and settings.generation_max_input_chars == 2048
    with pytest.raises(ValidationError):
        Settings(generation_timeout_seconds=10, generation_lease_seconds=15)


@pytest.mark.parametrize("args", [
    {"kind": "extract", "phase_id": "implement"}, {"kind": "extract", "max_classification": "public"},
    {"kind": "summary", "limit": 1}, {"kind": "extract", "limit": 101}, {"kind": "unknown"},
    {"kind": "extract", "provider": "external"},
])
def test_enqueue_contract_rejects_ignored_scope_options_and_external_providers(args):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_generation_enqueue", {"project_id": "p", **args})


@pytest.mark.parametrize("name", ["memory_generation_enqueue", "memory_generation_list", "memory_generation_retry"])
def test_generation_is_admin_only_and_project_bound(name):
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("u", "p", frozenset({"read", "write"})), name, {"project_id": "p"})
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("u", "p", frozenset({"admin"})), name, {"project_id": "other"})
    authorize_tool(Principal("u", "p", frozenset({"admin"})), name, {"project_id": "p"})


def test_summary_reads_need_only_read_scope():
    authorize_tool(Principal("u", "p", frozenset({"read"})), "memory_summary_read", {"project_id": "p"})
