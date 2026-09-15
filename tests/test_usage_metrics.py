"""Pure token semantics only; passing these tests does not mean usage is collected."""

import math

import pytest

from isekai_memory.continuity.usage_metrics import (
    MAX_TOKENS,
    Counter,
    Metrics,
    aggregate,
    normalize,
    unavailable,
    validate_revision,
)


def reported(value):
    return Counter(value, "reported")


def estimated(value, method="provider_estimate"):
    return Counter(value, "estimated", estimate_method=method)


def full(incoming=100, outgoing=20):
    return normalize({"input_total_tokens": reported(incoming), "output_total_tokens": reported(outgoing)})


def test_cache_and_reasoning_are_subsets_not_extra_consumption():
    value = normalize({"input_total_tokens": reported(100), "output_total_tokens": reported(20),
                       "cache_read_input_tokens": reported(60), "reasoning_output_tokens": reported(5)})
    assert value.as_dict()["total_tokens"]["value"] == 120
    assert aggregate([value])["reported"]["total_tokens"]["value"] == 120
    assert value.as_dict()["cache_write_input_tokens"]["value"] is None


@pytest.mark.parametrize("value", [-1, True, False, 1.0, math.nan, math.inf, MAX_TOKENS + 1, "100", None])
def test_reported_values_reject_noninteger_negative_and_oversize(value):
    with pytest.raises(ValueError):
        reported(value)


@pytest.mark.parametrize("args", [
    (0, "unavailable", None, "unsupported"), (None, "unavailable", None, None),
    (None, "unavailable", "provider_estimate", "unsupported"), (10, "estimated", None, None),
    (10, "estimated", "unknown_formula", None), (10, "reported", "provider_estimate", None),
    (10, "reported", None, "unsupported"), (None, "unavailable", None, "SECRET_REASON"),
])
def test_quality_and_reason_are_not_inferred(args):
    with pytest.raises(ValueError):
        Counter(*args)


def test_input_only_total_only_zero_and_unknown_remain_distinct():
    partial = normalize({"input_total_tokens": reported(100)})
    total_only = normalize({"total_tokens": reported(120)})
    zero = full(0, 0)
    missing = normalize({})
    assert partial.as_dict()["total_tokens"]["value"] is None
    assert total_only.as_dict()["input_total_tokens"]["value"] is None
    assert zero.as_dict()["total_tokens"]["value"] == 0
    assert aggregate([zero])["reported"]["total_tokens"]["value"] == 0
    assert aggregate([missing])["reported"]["total_tokens"]["value"] is None
    assert aggregate([])["reported"]["total_tokens"]["coverage"] == "no_observations"


@pytest.mark.parametrize("fields", [
    {"total_tokens": reported(119)}, {"cache_read_input_tokens": reported(101)},
    {"cache_write_input_tokens": reported(101)}, {"reasoning_output_tokens": reported(21)},
    {"cache_read_input_tokens": reported(60), "cache_write_input_tokens": reported(41)},
])
def test_inconsistent_totals_and_subsets_are_rejected(fields):
    with pytest.raises(ValueError):
        normalize({"input_total_tokens": reported(100), "output_total_tokens": reported(20)} | fields)


def test_total_overflow_is_rejected_before_aggregation():
    with pytest.raises(ValueError):
        full(MAX_TOKENS, 1)


def test_estimates_stay_separate_and_mixed_quality_does_not_fabricate_total():
    prompt = normalize({"input_total_tokens": estimated(18000, "prompt_length_div4")})
    mixed = normalize({"input_total_tokens": reported(100), "output_total_tokens": estimated(20)})
    assert mixed.as_dict()["total_tokens"]["omission_reason"] == "ambiguous"
    summary = aggregate([full(), prompt])
    assert summary["reported"]["input_total_tokens"]["value"] == 100
    assert summary["estimated"]["input_total_tokens"]["value"] == 18000
    assert summary["reported"]["total_tokens"]["value"] == 120
    assert summary["reported"]["total_tokens"]["coverage"] == "partial"
    assert summary["estimated"]["total_tokens"]["value"] is None


def test_absolute_revision_replaces_previous_counter_not_addition():
    previous, latest = full(100, 0), full(150, 0)
    validate_revision(previous, latest)
    validate_revision(latest, latest)
    assert aggregate([latest])["reported"]["total_tokens"]["value"] == 150
    with pytest.raises(ValueError):
        validate_revision(latest, previous)
    with pytest.raises(ValueError):
        validate_revision(latest, normalize({}))


def test_reported_replaces_same_scope_estimate_without_counting_both():
    guessed = normalize({"input_total_tokens": estimated(180)})
    actual = full(100, 20)
    validate_revision(guessed, actual)
    result = aggregate([actual])
    assert result["reported"]["total_tokens"]["value"] == 120
    assert result["estimated"]["input_total_tokens"]["value"] is None
    with pytest.raises(ValueError):
        validate_revision(actual, guessed)
    with pytest.raises(ValueError):
        validate_revision(guessed, normalize({"input_total_tokens": estimated(190, "prompt_length_div4")}))


def test_metric_dto_is_immutable_and_strict_without_raw_payload_fields():
    value = full()
    serialized = value.as_dict()
    assert Metrics.from_dict(serialized) == value
    serialized["input_total_tokens"]["value"] = 500
    assert value.as_dict()["input_total_tokens"]["value"] == 100
    for invalid in (value.as_dict() | {"prompt": "SECRET"}, {}, {"total_tokens": 100}):
        with pytest.raises(ValueError):
            Metrics.from_dict(invalid)
    with pytest.raises(ValueError):
        Counter.from_dict(reported(1).as_dict() | {"actor_id": "foreign"})
    with pytest.raises(ValueError):
        normalize({"prompt": unavailable()})
    with pytest.raises(ValueError):
        aggregate([value] * 10001)
