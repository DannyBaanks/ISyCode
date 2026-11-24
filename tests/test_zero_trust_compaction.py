"""Tests for zero-trust context limit learning, proactive compaction, side-effect safety,
and console tab title (`ISyCode | <Session name>`)."""
from __future__ import annotations

import asyncio
import json

import pytest

from isycode.continuity_capsule import (
    compaction_ceiling_tokens,
    estimate_request_tokens,
    shrink_request,
    update_tokens_per_char,
)
from isycode.provider_errors import (
    classify_provider_error,
    error_signals,
    parse_context_overflow_limit,
)
from isycode.providers import (
    heal_observed_context_limit,
    model_context_limit,
    record_model_metadata,
    record_observed_context_limit,
)
from isycode.streaming import StreamError


def test_error_signals_and_limit_parser_handle_spur_string_sse_error():
    spur_sse = json.dumps({
        "error": json.dumps({
            "error": {
                "message": (
                    "This model's maximum context length is 131072 tokens. "
                    "However, your prompt contains at least 131073 input tokens, "
                    "which exceeds this limit even without any output tokens."
                ),
                "type": "BadRequestError",
            }
        })
    })
    code, retry = error_signals(spur_sse)
    assert code == "context_length_exceeded"
    assert retry is None
    max_tokens, input_tokens = parse_context_overflow_limit(spur_sse)
    assert max_tokens == 131_072
    assert input_tokens == 131_073


def test_error_signals_and_limit_parser_handle_truncated_spur_string():
    truncated = json.dumps({
        "error": '{"error":{"message":"This model\'s maximum context length is 131072 tokens. However, your prompt contains at least 131073 input tokens","type":"BadRequestErro'
    })
    code, _ = error_signals(truncated)
    assert code == "context_length_exceeded"
    assert parse_context_overflow_limit(truncated) == (131_072, 131_073)


def test_limit_parser_ignores_ambiguous_transient_and_output_limit_errors():
    # Ambiguous prompt too long: classified as CONTEXT, but yields NO persisted hard limit.
    ambiguous = json.dumps({"error": {"message": "Prompt is too long"}})
    assert error_signals(ambiguous)[0] == "context_length_exceeded"
    assert parse_context_overflow_limit(ambiguous) == (None, None)

    # Rate limit / transient / output limit must never classify as context limit.
    rate = json.dumps({"error": {"message": "Rate limit exceeded: maximum context length is 131072 tokens"}})
    assert parse_context_overflow_limit(rate) == (None, None)

    out_limit = json.dumps({"error": {"message": "max_tokens must be less than 4096"}})
    assert error_signals(out_limit)[0] is None
    assert parse_context_overflow_limit(out_limit) == (None, None)

    corrupt = json.dumps({"error": {"message": "This model's maximum context length is 42 tokens"}})
    assert parse_context_overflow_limit(corrupt) == (None, None)


def test_observed_limit_trust_hierarchy_and_self_healing(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))

    # Misleading catalog advertises 1M context_length.
    record_model_metadata("openai", "spur-glm-5-3", {"context_length": 1_048_576})
    assert model_context_limit("openai", "spur-glm-5-3") == (1_048_576, "live-catalog")

    # Engine explicitly rejects with 131072 -> persisted as observed-limit.
    assert record_observed_context_limit("openai", "spur-glm-5-3", 131_072) == 131_072
    assert model_context_limit("openai", "spur-glm-5-3") == (131_072, "observed-limit")

    # Subsequent /v1/models refresh still advertising 1M must NOT overwrite observed-limit.
    record_model_metadata("openai", "spur-glm-5-3", {"context_length": 1_048_576})
    assert model_context_limit("openai", "spur-glm-5-3") == (131_072, "observed-limit")

    # vLLM max_model_len takes precedence over optimistic context_length on new models.
    record_model_metadata("openai", "vllm-capped", {
        "context_length": 1_048_576,
        "max_model_len": 65_536,
    })
    assert model_context_limit("openai", "vllm-capped") == (65_536, "live-catalog")

    # Self-healing: if a real successful response proves >131072 input tokens, drop stale cap.
    assert heal_observed_context_limit("openai", "spur-glm-5-3", 120_000) is False
    assert heal_observed_context_limit("openai", "spur-glm-5-3", 200_000) is True
    assert model_context_limit("openai", "spur-glm-5-3") == (None, "unknown")


def test_calibration_and_proactive_ceiling():
    assert compaction_ceiling_tokens(131_072) == 131_072 - 16_384
    assert compaction_ceiling_tokens(None) is None

    # Requires 2 plausible samples and ignores media/synthetic outliers.
    cal = update_tokens_per_char(None, 800, 2_000)
    assert cal is not None and cal[1] == 1
    cal = update_tokens_per_char(cal, 800, 2_000)
    assert cal is not None and cal[1] == 2 and cal[0] == pytest.approx(0.40)
    # Outlier (50 tokens/char) is rejected.
    assert update_tokens_per_char(cal, 100_000, 2_000) == cal

    messages = [{"role": "user", "content": "x" * 10_000}]
    # Anchor + calibrated delta: 100k measured + 500 output + delta
    projected = estimate_request_tokens(
        messages, None,
        calibration=cal,
        anchor_prompt_tokens=100_000,
        anchor_request_chars=8_000,
        anchor_output_tokens=500,
    )
    assert projected > 100_500


def test_shrink_request_preserves_executed_tool_receipts_without_repeating_side_effects():
    messages = [
        {"role": "system", "content": "Base system prompt"},
        {"role": "user", "content": "Old turn 1 " + "a" * 8_000},
        {"role": "assistant", "content": "Old reply 1 " + "b" * 8_000},
        {"role": "user", "content": "Run migration and check status"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_mutating_1",
                "type": "function",
                "function": {"name": "workspace_run", "arguments": '{"argv":["./migrate.sh"]}'},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_mutating_1",
            "content": json.dumps({"exit_code": 0, "stdout": "migrated 42 rows\n" + "z" * 12_000}),
        },
    ]
    # Current turn starts at index 3 ("Run migration and check status")
    shrunk, new_turn_start, removed = shrink_request(messages, 3, "Continuity capsule...", budget_chars=24_000)
    assert removed >= 2
    turn_slice = shrunk[new_turn_start:]
    # The assistant tool call and its tool result receipt MUST remain intact so the
    # model knows the side-effecting command already ran and does not re-execute it.
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in turn_slice)
    tool_msgs = [m for m in turn_slice if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_mutating_1"


def test_stream_error_with_context_limit_classifies_as_context():
    exc = StreamError(
        "provider reported a streaming API error",
        provider_code="context_length_exceeded",
        context_limit=131_072,
        prompt_tokens=131_073,
    )
    info = classify_provider_error(exc)
    assert info["error_kind"] == "CONTEXT"
    assert exc.context_limit == 131_072
    assert exc.prompt_tokens == 131_073


def test_format_terminal_title_and_sync():
    from isycode.tui import format_terminal_title

    assert format_terminal_title("Fibonalgge: estructuras y recurrencia", "ISyCo") == (
        "ISyCode | Fibonalgge: estructuras y recurrencia"
    )
    # Truncates long titles cleanly like OpenISy ("OC | ...")
    long_title = format_terminal_title("A" * 60, "ISyCo")
    assert long_title == "ISyCode | " + "A" * 37 + "…"

    # Falls back to workspace name when session is unnamed or generic
    assert format_terminal_title(None, "ISyCo") == "ISyCode | ISyCo"
    assert format_terminal_title("New session", "ISyCo") == "ISyCode | ISyCo"
    assert format_terminal_title("", "") == "ISyCode"

    # Strips ESC / BEL control characters to prevent terminal title escape injection
    sanitized = format_terminal_title("Safe\x1b]0;pwned\x07Title\nLine2", "ISyCo")
    assert "\x1b" not in sanitized
    assert "\x07" not in sanitized
    assert "\n" not in sanitized
    assert sanitized.startswith("ISyCode | Safe")


def test_tui_sync_terminal_title_emits_window_title(tmp_path, monkeypatch, capsys):
    from isycode.tui import TUIApp

    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "ISyCo"
    root.mkdir()
    monkeypatch.chdir(root)

    recorded_titles: list[str] = []

    async def scenario():
        app = TUIApp()
        monkeypatch.setattr(app.console, "set_window_title", recorded_titles.append)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            assert app.title == "ISyCode | ISyCo"
            app._active_chat_session_id = "ses_1"
            app._work_rows = [{"id": "ses_1", "title": "Fix auto-compaction"}]
            assert app._sync_terminal_title() == "ISyCode | Fix auto-compaction"
            assert app.title == "ISyCode | Fix auto-compaction"
            assert recorded_titles[-1] == "ISyCode | Fix auto-compaction"

            # Calling again with unchanged title is a no-op; renaming updates immediately.
            count_before = len(recorded_titles)
            app._sync_terminal_title()
            assert len(recorded_titles) == count_before
            app._sync_terminal_title("Renamed session")
            assert app.title == "ISyCode | Renamed session"
            assert recorded_titles[-1] == "ISyCode | Renamed session"

    with capsys.disabled():
        asyncio.run(scenario())


def test_tui_learns_explicit_limit_on_overflow_without_repeating_tools(tmp_path, monkeypatch, capsys):
    from isycode.providers import save_provider_selection
    from isycode.tui import TUIApp
    from isycode.workspace_authority import WorkspaceAuthority

    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-zero-trust")
    monkeypatch.delenv("ISYCODE_PROVIDER", raising=False)
    monkeypatch.delenv("ISYCODE_MODEL", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    (root / "notes.txt").write_text("tool-result-marker\n", encoding="utf-8")
    monkeypatch.chdir(root)
    auth = WorkspaceAuthority(root)
    auth.set_mode("classic")
    save_provider_selection("openai", "spur-glm-5-3")
    record_model_metadata("openai", "spur-glm-5-3", {"context_length": 1_048_576})

    calls: list[list[dict]] = []

    async def complete(provider, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            return {
                "text": "",
                "tool_calls": [{
                    "id": "r1",
                    "type": "function",
                    "function": {"name": "workspace_read", "arguments": '{"path": "notes.txt"}'},
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            }
        if len(calls) == 2:
            raise StreamError(
                "provider reported a streaming API error",
                provider_code="context_length_exceeded",
                context_limit=131_072,
                prompt_tokens=131_073,
            )
        return {
            "text": "Finished without re-running tools.",
            "tool_calls": [],
            "usage": {"prompt_tokens": 4_000, "completion_tokens": 20},
        }

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            assert app.title == "ISyCode | project"
            app._history = [
                {"role": "user", "content": "turn 1 " + "x" * 100},
                {"role": "assistant", "content": "reply 1 " + "y" * 100},
            ]
            dispatched: list[str] = []
            original = app._dispatch_chat_tool

            async def counting(call, *args, **kwargs):
                dispatched.append(call["id"])
                return await original(call, *args, **kwargs)

            app._dispatch_chat_tool = counting
            await app._run_chat("Read notes.txt")
            assert dispatched == ["r1"]
            assert len(calls) == 3
            # Explicit 131072 limit persisted as observed-limit despite 1M catalog!
            assert model_context_limit("openai", "spur-glm-5-3") == (131_072, "observed-limit")
            assert app._context_window() == (131_072, "observed-limit")

    with capsys.disabled():
        asyncio.run(scenario())


