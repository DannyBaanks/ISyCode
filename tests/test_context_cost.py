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


def test_usage_panel_draws_a_bounded_bar_and_never_divides_by_an_unknown_window():
    from isycode.context_meter import usage_panel
    messages = [{"role": "user", "content": "x" * 4000}]
    for width in (14, 18, 30):
        known = usage_panel(messages, width, "4.0 t/s · 30 tok", provider_limit_tokens=200_000,
                            reported_tokens=150_000).plain.splitlines()
        assert len(known) == 3 and all(len(row) == width for row in known)
        assert "75%" in known[1] and known[1].count("█") > known[1].count("░")
        unknown = usage_panel(messages, width, "t/s — · 30 +? tok").plain.splitlines()
        assert unknown[1].rstrip().endswith("?") and "█" not in unknown[1] and "%" not in unknown[1]
        assert "+? tok" in unknown[2]
    snap = usage_panel(messages, 24, "x", provider_limit_tokens=1_000_000, limit_source="snapshot").plain
    assert "ctx ~1k/≈1M" in snap  # estimate and snapshot window are both marked
    live = usage_panel(messages, 24, "x", provider_limit_tokens=1_000_000, reported_tokens=900).plain
    assert "ctx 900/1M" in live
