"""Tests for provider quota recognition, ModelsScreen quota panel, and ACP transcript fitting."""
from __future__ import annotations

import asyncio
import datetime as dt
import json

from textual.widgets import Static

from isycode.antigravity_connector import ACP_PROMPT_BUDGET_BYTES, AntigravityConnector
from isycode.provider_quotas import (
    clear_provider_quota,
    format_quota_bar,
    get_provider_quota,
    parse_codex_rate_limits,
    parse_deepseek_balance_payload,
    parse_http_rate_limit_headers,
    parse_openrouter_key_payload,
    quota_panel_lines,
    record_antigravity_quota,
    record_codex_rate_limits,
    record_http_rate_limits,
)
from isycode.tui import ModelsScreen, TUIApp, plain_text
from test_daily_tui import configure


SAMPLE_ANTIGRAVITY_QUOTA = {
    "ok": True,
    "buckets": [
        {
            "group": "Gemini",
            "id": "gemini-5h",
            "name": "Gemini 5h",
            "window": "5h",
            "family": "gemini",
            "pct": 80.0,
            "reset_time": "2026-11-25T22:00:00Z",
        },
        {
            "group": "Gemini",
            "id": "gemini-7d",
            "name": "Gemini 7d",
            "window": "weekly",
            "family": "gemini",
            "pct": 62.0,
            "reset_time": "2026-11-30T00:00:00Z",
        },
        {
            "group": "Argon",
            "id": "argon-5h",
            "name": "Argon 5h",
            "window": "5h",
            "family": "argon",
            "pct": 100.0,
            "reset_time": "2026-11-25T22:00:00Z",
        },
    ],
    "families": {
        "gemini": {
            "5h": {"pct": 80.0, "reset_time": "2026-11-25T22:00:00Z"},
            "weekly": {"pct": 62.0, "reset_time": "2026-11-30T00:00:00Z"},
        },
        "argon": {
            "5h": {"pct": 100.0, "reset_time": "2026-11-25T22:00:00Z"},
        },
    },
    "min_pct": 62.0,
    "updated_at": "2026-11-25T18:00:00Z",
}


def test_parse_codex_rate_limits_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    now = dt.datetime(2026, 11, 25, 18, 0, 0, tzinfo=dt.timezone.utc)
    payload = {
        "rateLimits": {
            "planType": "plus",
            "primary": {"usedPercent": 15, "windowDurationMins": 300, "resetsAt": int(now.timestamp()) + 7200},
            "secondary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": int(now.timestamp()) + 86400 * 3},
            "credits": {"hasCredits": True, "unlimited": False, "balance": "12.50"},
        },
        "rateLimitsByLimitId": {
            "gpt-5-codex": {
                "limitName": "GPT-5 Codex",
                "normalModelSlug": "gpt-5-codex",
                "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": int(now.timestamp()) + 3600},
            }
        },
    }
    parsed = parse_codex_rate_limits(payload)
    assert parsed is not None
    assert parsed["plan"] == "plus"
    assert parsed["credits"]["label"] == "$12.50"
    assert parsed["buckets"][0]["label"] == "5h"
    assert parsed["buckets"][0]["remaining_pct"] == 85.0
    assert parsed["buckets"][1]["label"] == "7d"
    assert parsed["buckets"][1]["remaining_pct"] == 60.0

    record_codex_rate_limits(payload)
    loaded = get_provider_quota("chatgpt")
    assert loaded is not None and loaded["plan"] == "plus"

    lines = quota_panel_lines("chatgpt", "gpt-5-codex", now=now)
    rendered = "\n".join(text for text, _ in lines)
    assert "plus" in rendered
    assert "85%" in rendered
    assert "60%" in rendered
    assert "$12.50" in rendered


def test_parse_http_rate_limit_headers_openai_groq_and_anthropic(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    groq_headers = {
        "X-RateLimit-Limit-Requests": "30",
        "X-RateLimit-Remaining-Requests": "27",
        "X-RateLimit-Reset-Requests": "12s",
        "X-RateLimit-Limit-Tokens": "12000",
        "X-RateLimit-Remaining-Tokens": "9600",
        "X-RateLimit-Reset-Tokens": "4s",
    }
    snap = record_http_rate_limits("groq", groq_headers, model="openai/gpt-oss-120b")
    assert snap is not None
    assert len(snap["buckets"]) == 2
    assert snap["buckets"][0]["remaining_pct"] == 90.0
    assert snap["buckets"][1]["remaining_pct"] == 80.0

    anthropic_headers = {
        "anthropic-ratelimit-requests-limit": "100",
        "anthropic-ratelimit-requests-remaining": "10",
        "anthropic-ratelimit-requests-reset": "2026-11-25T19:00:00Z",
        "anthropic-ratelimit-unified-5h-utilization": "0.35",
        "anthropic-ratelimit-unified-7d-utilization": "0.85",
    }
    anth = parse_http_rate_limit_headers(anthropic_headers, provider="anthropic")
    assert anth is not None
    labels = {b["label"]: b["remaining_pct"] for b in anth["buckets"]}
    assert labels["5h"] == 65.0
    assert labels["7d"] == 15.0
    assert labels["Requests"] == 10.0

    # Headers with no rate-limit data return None and never fabricate quota.
    assert parse_http_rate_limit_headers({"content-type": "application/json"}, provider="openai") is None
    assert format_quota_bar(50.0, 10) == "█████░░░░░"


def test_parse_openrouter_and_deepseek_payloads():
    or_snap = parse_openrouter_key_payload({
        "data": {
            "limit": 10.0,
            "limit_remaining": 4.2,
            "usage": 5.8,
            "usage_daily": 0.35,
            "is_free_tier": False,
        }
    })
    assert or_snap is not None
    assert or_snap["credits"]["label"] == "$4.20 / $10.00"
    assert or_snap["buckets"][0]["remaining_pct"] == 42.0
    assert or_snap["plan"] == "paid"

    ds_snap = parse_deepseek_balance_payload({
        "is_available": True,
        "balance_infos": [{"currency": "USD", "total_balance": "18.75"}],
    })
    assert ds_snap is not None
    assert ds_snap["credits"]["label"] == "$18.75"
    assert ds_snap["plan"] == "available"


def test_models_screen_renders_provider_quotas_in_detail_pane(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    clear_provider_quota("antigravity")
    clear_provider_quota("groq")
    record_antigravity_quota(SAMPLE_ANTIGRAVITY_QUOTA)
    record_http_rate_limits("groq", {
        "x-ratelimit-limit-requests": "30",
        "x-ratelimit-remaining-requests": "24",
        "x-ratelimit-reset-requests": "5s",
    })

    entries = [
        {"label": "Gemini 4 Neon Medium", "kind": "model", "value": "antigravity|gemini-4-neon-medium"},
        {"label": "Gemini 4 Argon Medium", "kind": "model", "value": "antigravity|gemini-4-argon-medium"},
    ]

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(130, 42)) as pilot:
            await app.wait_for_ready()
            screen = ModelsScreen(entries, provider_scope="antigravity")
            app.push_screen(screen)
            await pilot.pause(0.1)

            screen.show_details("antigravity", "gemini-4-neon-medium")
            detail = plain_text(screen.query_one("#model-detail", Static))
            assert "Gemini" in detail
            assert "80%" in detail
            assert "62%" in detail
            assert "Argon" in detail

            # Switching to Argon model highlights Argon's 100% bucket.
            screen.show_details("antigravity", "gemini-4-argon-medium")
            detail_argon = plain_text(screen.query_one("#model-detail", Static))
            assert "Argon" in detail_argon
            assert "100%" in detail_argon

            # Switching to an API-key provider with observed headers shows its rate limits.
            screen.show_details("groq", "openai/gpt-oss-120b")
            detail_groq = plain_text(screen.query_one("#model-detail", Static))
            assert "80%" in detail_groq
            assert "24/30" in detail_groq

            # Provider with no observed quota yet shows honest non-guessed state.
            screen.show_details("mistral", "mistral-small-latest")
            detail_mistral = plain_text(screen.query_one("#model-detail", Static))
            assert "Not reported yet" in detail_mistral or "Sin reporte" in detail_mistral

    with capsys.disabled():
        asyncio.run(scenario())


def test_antigravity_fit_acp_transcript_prevents_acp_tail_truncation_loop():
    huge_git_status = "M file.py\n" * 45_000  # ~450 KB -> previously triggered <truncated 378749 bytes>
    messages = [
        {"role": "system", "content": "You are ISyCode."},
        {"role": "system", "content": "Untrusted historical tool results:\n" + "h" * 50_000},
        {"role": "user", "content": "Run all tools"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "git_status", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": huge_git_status},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c2", "function": {"name": "git_diff", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "diff --git a/x.py b/x.py\n+ok"},
        {"role": "user", "content": "Continue with CRUD in /tmp"},
    ]
    fitted = AntigravityConnector._fit_acp_transcript(messages, budget_bytes=ACP_PROMPT_BUDGET_BYTES)
    encoded = json.dumps({"messages": fitted}, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= ACP_PROMPT_BUDGET_BYTES
    # Valid JSON with newest user prompt and newest tool receipt preserved intact!
    assert fitted[-1] == {"role": "user", "content": "Continue with CRUD in /tmp"}
    assert any(m.get("tool_call_id") == "c2" and "+ok" in m.get("content", "") for m in fitted)
    # Normal small transcripts stay completely untouched.
    small = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    assert AntigravityConnector._fit_acp_transcript(small) == small
