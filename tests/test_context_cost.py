from isycode.context_meter import compact_context_label, context_snapshot
from isycode.usage import CostBucket


def test_context_snapshot_is_explicitly_estimated_when_provider_limit_is_unknown():
    snapshot = context_snapshot([
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": "y" * 200},
    ])
    assert snapshot["characters"] == 600
    assert snapshot["estimated_tokens"] == 150
    assert snapshot["provider_limit_tokens"] is None
    assert snapshot["status"] == "estimated"


def test_context_meter_uses_provider_usage_and_reports_window_source():
    snapshot = context_snapshot(
        [{"role": "user", "content": "x" * 400}],
        provider_limit_tokens=200_000,
        reported_tokens=12_000,
        limit_source="live-catalog",
    )
    assert snapshot == {
        "characters": 400,
        "estimated_tokens": 100,
        "used_tokens": 12_000,
        "provider_limit_tokens": 200_000,
        "used_source": "provider-usage",
        "limit_source": "live-catalog",
        "percent": 6,
        "status": "measured",
    }
    assert compact_context_label([], provider_limit_tokens=200_000,
                                 reported_tokens=12_000) == "ctx 12k/200k 6%"


def test_context_meter_marks_estimated_usage_and_never_divides_by_unknown_limit():
    assert compact_context_label([{"role": "user", "content": "x" * 400}]) == "ctx ~100 est · window ?"


def test_context_meter_keeps_estimate_mark_with_a_known_model_window():
    assert compact_context_label([{"role": "user", "content": "x" * 400}],
                                 provider_limit_tokens=200_000) == "ctx ~100/200k 0%"


def test_cost_bucket_never_turns_unknown_into_zero():
    unknown = CostBucket.unknown()
    included = CostBucket.included("subscription")
    estimated = CostBucket.estimated(0.0123, source="configured-rate")

    assert unknown.to_state() == {"status": "unknown"}
    assert "usd" not in unknown.to_state()
    assert included.to_state() == {"status": "included", "source": "subscription"}
    assert estimated.to_state() == {
        "status": "estimated", "usd": 0.0123, "source": "configured-rate",
    }
