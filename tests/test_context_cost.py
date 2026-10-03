from isycode.context_meter import context_snapshot
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
