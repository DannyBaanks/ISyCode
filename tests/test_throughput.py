"""Output tokens per second come from a reported count and a measured duration."""
from isycode.throughput import ThroughputMeter, completion_tokens, format_rate, measure_rate


def test_rate_needs_a_reported_count_and_a_positive_duration():
    assert completion_tokens({"completion_tokens": 12}) == 12
    assert completion_tokens({"output_tokens": 4}) == 4
    assert completion_tokens({"completion_tokens": True}) is None
    assert completion_tokens({"completion_tokens": -1}) is None
    assert completion_tokens({"completion_tokens": 10**12 + 1}) is None
    assert completion_tokens("nope") is None
    assert measure_rate({"completion_tokens": 10}, 2) == 5
    assert measure_rate({"completion_tokens": 10}, 0) is None
    assert measure_rate({"completion_tokens": 10}, True) is None
    assert measure_rate({}, 2) is None
    assert format_rate(None) == "t/s —"
    assert format_rate(None, measuring=True) == "measuring t/s"
    assert format_rate(12.34) == "12.3 t/s"
    assert format_rate(120) == "120 t/s"

    meter = ThroughputMeter()
    assert meter.note({}, 1) is None
    assert meter.last_rate is None
    meter.measuring = True
    measuring = meter.widget_text(30, True, "ctx ~1 est")
    assert measuring.startswith("measuring t/s")
    assert "30 +? tok" in measuring
    assert meter.note({"completion_tokens": 8}, 2) == 4
    assert meter.measured_turns == 1
    assert meter.last_rate == 4
    meter.measuring = False
    shown = meter.widget_text(30, False, "ctx ~1 est")
    assert shown.startswith("4.0 t/s")
    assert "30 tok" in shown
    assert "+?" not in shown
    assert "ctx ~1 est" in shown
