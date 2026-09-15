"""Pure normalized token arithmetic; no collection, authentication, receipts or I/O.

Inputs are already normalized, non-overlapping counters. Cache read/write are
disjoint subsets of input; reasoning is a subset of output. Host adapters must
verify these meanings before using this contract, not guess from field names.
"""

from dataclasses import dataclass

MAX_TOKENS = 10**12
MAX_AGGREGATE_UNITS = 10000
FIELDS = ("input_total_tokens", "output_total_tokens", "total_tokens",
          "cache_read_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens")
QUALITIES = ("reported", "estimated", "unavailable")
METHODS = ("prompt_length_div4", "provider_estimate")
REASONS = ("not_reported", "unsupported", "truncated", "ambiguous", "not_observed",
           "awaiting_result", "invalid_report", "not_applicable", "outside_scope")


@dataclass(frozen=True)
class Counter:
    value: int | None
    quality: str
    estimate_method: str | None = None
    omission_reason: str | None = None

    def __post_init__(self):
        if self.quality not in QUALITIES:
            raise ValueError("Unknown counter quality")
        if self.quality == "unavailable":
            if self.value is not None or self.estimate_method is not None or self.omission_reason not in REASONS:
                raise ValueError("Unavailable counters need a reason, never a fabricated zero")
        else:
            if type(self.value) is not int or not 0 <= self.value <= MAX_TOKENS or self.omission_reason is not None:
                raise ValueError("Token counts must be bounded nonnegative integers")
            if ((self.quality == "reported" and self.estimate_method is not None)
                    or (self.quality == "estimated" and self.estimate_method not in METHODS)):
                raise ValueError("Estimated counts require a recognized method; reported counts are not estimates")

    def comparable(self, other):
        return self.quality != "unavailable" and self.quality == other.quality and self.estimate_method == other.estimate_method

    def as_dict(self):
        return {"value": self.value, "quality": self.quality,
                "estimate_method": self.estimate_method, "omission_reason": self.omission_reason}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"value", "quality", "estimate_method", "omission_reason"}:
            raise ValueError("Counter fields do not match the pinned contract")
        return cls(**value)


def unavailable(reason="not_reported"):
    return Counter(None, "unavailable", omission_reason=reason)


@dataclass(frozen=True)
class Metrics:
    counters: tuple[Counter, ...]

    def __post_init__(self):
        if type(self.counters) is not tuple or len(self.counters) != len(FIELDS) or any(not isinstance(value, Counter) for value in self.counters):
            raise ValueError("A normalized snapshot requires all six counters")
        incoming, outgoing, total, cache_read, cache_write, reasoning = self.counters
        if incoming.comparable(outgoing) and total.comparable(incoming) and total.value != incoming.value + outgoing.value:
            raise ValueError("Input/output/total counters disagree")
        for parent, subset in ((total, incoming), (total, outgoing), (incoming, cache_read),
                               (incoming, cache_write), (outgoing, reasoning)):
            if parent.comparable(subset) and subset.value > parent.value:
                raise ValueError("A reported subset cannot exceed its parent counter")
        if incoming.comparable(cache_read) and incoming.comparable(cache_write) and cache_read.value + cache_write.value > incoming.value:
            raise ValueError("Normalized disjoint cache components exceed input")

    def as_dict(self):
        return {name: counter.as_dict() for name, counter in zip(FIELDS, self.counters, strict=True)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(FIELDS):
            raise ValueError("Metric fields do not match the pinned contract")
        return cls(tuple(Counter.from_dict(value[name]) for name in FIELDS))


def normalize(fields):
    """Fill missing fields, deriving a total only from comparable known input/output."""
    if not isinstance(fields, dict) or not set(fields) <= set(FIELDS) or any(not isinstance(value, Counter) for value in fields.values()):
        raise ValueError("Unknown metric or unnormalized counter")
    values = {name: fields.get(name, unavailable()) for name in FIELDS}
    incoming, outgoing = values["input_total_tokens"], values["output_total_tokens"]
    if "total_tokens" not in fields and incoming.comparable(outgoing):
        values["total_tokens"] = Counter(incoming.value + outgoing.value, incoming.quality, incoming.estimate_method)
    elif "total_tokens" not in fields and incoming.value is not None and outgoing.value is not None:
        values["total_tokens"] = unavailable("ambiguous")
    return Metrics(tuple(values[name] for name in FIELDS))


def validate_revision(previous, current):
    """One absolute counter epoch: don't silently reset or downgrade known data.

    A reported replacement may be smaller than its former estimate. It replaces
    that estimate; the caller must never sum both versions of the same unit.
    Identity, sequence/digest replay and finalization are separate ledger checks.
    """
    if not isinstance(previous, Metrics) or not isinstance(current, Metrics):
        raise ValueError("Revisions require normalized snapshots")
    for old, new in zip(previous.counters, current.counters, strict=True):
        if old.quality == "unavailable":
            continue
        if old.quality == "estimated" and new.quality == "reported":
            continue
        if not old.comparable(new) or new.value < old.value:
            raise ValueError("Counters cannot reset, disappear or change method within an epoch")


def aggregate(snapshots):
    """Aggregate supplied *latest, non-overlapping* units, never a list-page total.

    Callers must resolve receipt revisions, parent/child overlap and permission
    scope first. This pure helper cannot infer missing external CLI activity.
    """
    if (not isinstance(snapshots, (list, tuple)) or len(snapshots) > MAX_AGGREGATE_UNITS
            or any(not isinstance(item, Metrics) for item in snapshots)):
        raise ValueError("Aggregate input must be a bounded set of normalized snapshots")
    result = {"semantics_version": 1, "observed_units": len(snapshots), "coverage_scope": "supplied_units_only"}
    for quality in ("reported", "estimated"):
        totals = {}
        for index, name in enumerate(FIELDS):
            known = [item.counters[index] for item in snapshots if item.counters[index].quality == quality]
            totals[name] = {"value": sum(value.value for value in known) if known else None,
                            "known_units": len(known), "missing_units": len(snapshots) - len(known),
                            "coverage": "no_observations" if not snapshots else "complete" if len(known) == len(snapshots) else "partial"}
            if quality == "estimated":
                totals[name]["estimate_methods"] = sorted({value.estimate_method for value in known})
        result[quality] = totals
    reasons = {}
    for snapshot in snapshots:
        for value in snapshot.counters:
            if value.quality == "unavailable":
                reasons[value.omission_reason] = reasons.get(value.omission_reason, 0) + 1
    result["unavailable_field_counts"] = reasons
    return result
