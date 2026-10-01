"""Pure provider-reported token accounting and conservative budget checks."""

import pytest

from isycode.usage import UsageLedger


LIMIT = 10**12


def test_empty_ledger_is_unlimited_and_has_no_reported_tokens():
    ledger = UsageLedger()
    assert ledger.to_state() == dict(requests=0, input_tokens=0, output_tokens=0, unknown_requests=0)
    assert ledger.allowed()
    assert ledger.remaining() is None
    assert ledger.remaining(100) == 100
    assert "0" in ledger.label()
    assert "$" not in ledger.label()


def test_both_provider_shapes_accumulate_only_reported_input_and_output():
    ledger = UsageLedger()
    ledger.record({"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 999})
    ledger.record({"input_tokens": 20, "output_tokens": 5})
    assert ledger.to_state() == dict(requests=2, input_tokens=32, output_tokens=13, unknown_requests=0)
    assert ledger.allowed(46)
    assert not ledger.allowed(45)
    assert not ledger.allowed(40)
    assert ledger.remaining(46) == 1
    assert ledger.remaining(40) == 0
    assert "unknown" not in ledger.label().lower()


@pytest.mark.parametrize("usage", [None, {}, [], "usage", {"total_tokens": 7}])
def test_missing_or_malformed_usage_is_unknown_and_blocks_configured_budget(usage):
    ledger = UsageLedger()
    ledger.record(usage)
    assert ledger.to_state() == dict(requests=1, input_tokens=0, output_tokens=0, unknown_requests=1)
    assert ledger.allowed(0)
    assert not ledger.allowed(100)
    assert ledger.remaining(100) == 100
    assert "unknown" in ledger.label().lower()
    assert "at least" in ledger.label().lower()


@pytest.mark.parametrize("bad", [True, False, -1, 1.0, "1", None, LIMIT + 1])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_invalid_counter_preserves_the_other_reported_counter_and_marks_unknown(field, bad):
    usage = {"input_tokens": 7, "output_tokens": 3, field: bad}
    ledger = UsageLedger()
    ledger.record(usage)
    assert ledger.requests == 1
    assert ledger.unknown_requests == 1
    assert ledger.input_tokens == (0 if field == "input_tokens" else 7)
    assert ledger.output_tokens == (0 if field == "output_tokens" else 3)


def test_partial_usage_and_mixed_provider_fields_are_not_treated_as_complete():
    ledger = UsageLedger()
    ledger.record({"prompt_tokens": 4})
    ledger.record({"input_tokens": 8, "completion_tokens": 9})
    assert ledger.to_state() == dict(requests=2, input_tokens=12, output_tokens=0, unknown_requests=2)


def test_zero_reported_usage_is_known():
    ledger = UsageLedger()
    ledger.record({"input_tokens": 0, "output_tokens": 0})
    assert ledger.unknown_requests == 0
    assert ledger.allowed(1)


def test_anthropic_cache_read_and_creation_tokens_consume_input_budget():
    ledger = UsageLedger()
    ledger.record({"input_tokens": 5, "output_tokens": 2,
                   "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10})
    assert ledger.to_state() == dict(requests=1, input_tokens=45, output_tokens=2, unknown_requests=0)
    assert not ledger.allowed(47)
    assert ledger.remaining(50) == 3


@pytest.mark.parametrize("field", ["cache_read_input_tokens", "cache_creation_input_tokens"])
@pytest.mark.parametrize("bad", [True, False, -1, 1.0, "1", None, LIMIT + 1])
def test_malformed_anthropic_cache_counter_marks_unknown_and_keeps_known_usage(field, bad):
    ledger = UsageLedger()
    ledger.record({"input_tokens": 5, "output_tokens": 2, field: bad})
    assert ledger.to_state() == dict(requests=1, input_tokens=5, output_tokens=2, unknown_requests=1)
    assert not ledger.allowed(100)


def test_anthropic_cache_input_overflow_is_bounded_and_unknown():
    ledger = UsageLedger()
    ledger.record({"input_tokens": LIMIT, "output_tokens": 2, "cache_read_input_tokens": 1})
    assert ledger.input_tokens == LIMIT
    assert ledger.unknown_requests == 1
    assert not ledger.allowed(LIMIT)


def test_cache_only_anthropic_usage_keeps_cache_tokens_but_is_unknown():
    ledger = UsageLedger()
    ledger.record({"cache_read_input_tokens": 9})
    assert ledger.to_state() == dict(requests=1, input_tokens=9, output_tokens=0, unknown_requests=1)


def test_openai_cached_tokens_are_already_in_prompt_tokens():
    ledger = UsageLedger()
    ledger.record({"prompt_tokens": 12, "completion_tokens": 3,
                   "prompt_tokens_details": {"cached_tokens": 10}})
    assert ledger.to_state() == dict(requests=1, input_tokens=12, output_tokens=3, unknown_requests=0)


def test_state_roundtrip_copies_counters_without_granting_authority():
    state = dict(requests=2, input_tokens=10, output_tokens=5, unknown_requests=1)
    ledger = UsageLedger.from_state(state)
    state["input_tokens"] = 999
    exported = ledger.to_state()
    assert exported == dict(requests=2, input_tokens=10, output_tokens=5, unknown_requests=1)
    exported["input_tokens"] = 888
    assert ledger.input_tokens == 10
    assert not ledger.allowed(100)


@pytest.mark.parametrize("state", [None, [], {}, {"requests": 0},
    dict(requests=0, input_tokens=0, output_tokens=0, unknown_requests=0, grants=["provider"]),
    dict(requests=0, input_tokens=0, output_tokens=0, unknown_requests=1)])
def test_state_requires_exact_counters_and_consistent_unknown_requests(state):
    with pytest.raises(ValueError):
        UsageLedger.from_state(state)


@pytest.mark.parametrize("bad", [True, False, -1, 1.0, "1", None, LIMIT + 1])
@pytest.mark.parametrize("field", ["requests", "input_tokens", "output_tokens", "unknown_requests"])
def test_constructor_and_state_reject_invalid_counters(field, bad):
    state = dict(requests=1, input_tokens=0, output_tokens=0, unknown_requests=0)
    state[field] = bad
    with pytest.raises(ValueError):
        UsageLedger(**state)
    with pytest.raises(ValueError):
        UsageLedger.from_state(state)


@pytest.mark.parametrize("budget", [True, -1, 1.0, "1", None, LIMIT + 1])
def test_invalid_budget_is_rejected(budget):
    ledger = UsageLedger()
    with pytest.raises(ValueError):
        ledger.allowed(budget)
    with pytest.raises(ValueError):
        ledger.remaining(budget)


def test_counter_overflow_remains_bounded_unknown_and_conservative():
    ledger = UsageLedger(requests=LIMIT, input_tokens=LIMIT, output_tokens=LIMIT)
    ledger.record({"input_tokens": 1, "output_tokens": 2})
    assert ledger.to_state() == dict(requests=LIMIT, input_tokens=LIMIT, output_tokens=LIMIT, unknown_requests=1)
    assert not ledger.allowed(LIMIT)
    assert "at least" in ledger.label().lower()
    assert f"at least {LIMIT} requests" in ledger.label().lower()
