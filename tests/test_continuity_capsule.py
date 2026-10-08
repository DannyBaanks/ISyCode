"""ADR 0009: a deterministic continuity capsule covers every loss of context."""
import asyncio
import json

import pytest

from isycode import continuity_recovery
from isycode.agent_loop import ELIDED_TOOL_RESULT, total_chars
from isycode.continuity_capsule import (
    ASSUMED_WINDOW_TOKENS, CAPSULE_HEADER, MIN_BUDGET_CHARS, SUBAGENT_CAPSULE_CHARS,
    build_capsule, history_budget_chars, is_capsule, plan_context, shrink_request)
from isycode.continuity_recovery import plan_recovery
from isycode.provider_errors import classify_provider_error, error_signals
from isycode.providers import record_model_metadata, save_model_slot
from isycode.streaming import StreamError
from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def note(name, arguments, result):
    return {"name": name, "arguments": json.dumps(arguments), "result": result}


def conversation(turns, size=2_000):
    history = []
    for index in range(turns):
        history.append({"role": "user", "content": f"request-{index} " + "u" * size})
        history.append({"role": "assistant", "content": f"answer-{index} " + "a" * size})
    return history


NOTES = [
    note("workspace_read", {"path": "src/parser.py"}, "def parse(): ...\n" * 400),
    note("workspace_edit", {"path": "src/parser.py"}, json.dumps({"status": "written"})),
    note("workspace_run", {"argv": ["pytest", "-q"]}, json.dumps({"exit_code": 1})),
    note("workspace_write", {"path": "src/new.py"}, json.dumps({"error": "denied by the user"})),
]


# ── The engine ─────────────────────────────────────────────────────────
def test_a_conversation_that_fits_is_sent_unchanged():
    history = conversation(3, size=100)
    plan = plan_context(history, NOTES[:1], budget_chars=1_000_000)
    assert plan["history"] == history and plan["older"] == [] and plan["capsule"] == ""
    assert "def parse()" in plan["notes"]                       # the full notes, as before


def test_overflow_keeps_recent_turns_and_carries_the_rest_in_the_capsule():
    history = conversation(40)
    budget = 40_000
    plan = plan_context(history, NOTES, budget_chars=budget,
                        tasks=[{"title": "Fix the parser", "status": "in_progress"}],
                        idea_box="Next: rerun the parser tests")
    assert plan["older"] and plan["history"][0]["role"] == "user"
    assert plan["older"] + plan["history"] == history           # nothing reordered or lost
    assert total_chars(plan["history"]) + len(plan["capsule"]) <= budget
    assert plan["notes"] == ""                                  # the capsule replaces full notes
    capsule = plan["capsule"]
    assert capsule.startswith(CAPSULE_HEADER)
    assert "request-0" in capsule                               # what the user asked earlier
    assert "changed · edit src/parser.py · written" in capsule
    assert "changed · write src/new.py · failed: denied by the user" in capsule
    assert "ran · pytest -q · exit 1" in capsule
    assert "[in_progress] Fix the parser" in capsule and "rerun the parser tests" in capsule
    assert "answer-0" not in capsule                            # assistant prose is not replayed


def test_the_capsule_respects_its_budget_and_says_what_it_left_out():
    capsule = build_capsule(budget_chars=1_500, tool_history=NOTES,
                            older_messages=conversation(30, size=50))
    assert len(capsule) <= 1_500 and capsule.startswith(CAPSULE_HEADER)
    assert "older entries omitted" in capsule
    assert "request-29" in capsule and "request-0 " not in capsule   # newest kept


def test_a_long_narrative_summary_is_cut_not_dropped():
    capsule = build_capsule(budget_chars=3_000, summary="NOTES-START " + "n" * 10_000,
                            older_messages=conversation(5, size=50))
    assert len(capsule) <= 3_000 and "NOTES-START" in capsule and "request-4" in capsule


def test_the_capsule_carries_no_secret_call_id_or_grant():
    history = [note("workspace_read", {"path": ".env"}, 'api_key = "sk-live-123456"'),
               note("webfetch", {"url": "https://x.test", "authorization": "Bearer abc"}, "ok")]
    capsule = build_capsule(budget_chars=10_000, tool_history=history)
    assert "sk-live-123456" not in capsule and "Bearer abc" not in capsule
    assert "tool_call_id" not in capsule and "never authorization" in capsule


def test_the_budget_follows_the_model_window():
    assert history_budget_chars(None) == history_budget_chars(ASSUMED_WINDOW_TOKENS)
    assert history_budget_chars(8_000) == MIN_BUDGET_CHARS
    assert history_budget_chars(1_000_000) > history_budget_chars(128_000) > history_budget_chars(32_000)


def test_shrinking_a_rejected_request_keeps_the_turn_and_every_call_answered():
    system = {"role": "system", "content": "You are ISyCode."}
    old_notes = {"role": "system", "content": "Untrusted historical tool results: ...\n" + "x" * 5_000}
    earlier = conversation(10)
    prompt = {"role": "user", "content": "Fix the parser"}
    calls = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": "workspace_read", "arguments": "{}"}}]}
        for i in range(3)]
    turn = [prompt]
    for index, call in enumerate(calls):
        turn += [call, {"role": "tool", "tool_call_id": f"c{index}", "content": "r" * 20_000}]
    messages = [system, old_notes] + earlier + turn
    shrunk, start, removed = shrink_request(messages, 2 + len(earlier), "CAPSULE", 30_000)
    assert shrunk[0] == system and shrunk[1] == {"role": "system", "content": "CAPSULE"}
    assert shrunk[start] == prompt and old_notes not in shrunk
    assert not any(message in shrunk for message in earlier)
    ids = [message["tool_call_id"] for message in shrunk if message["role"] == "tool"]
    assert ids == ["c0", "c1", "c2"]                             # every call still answered
    assert [m["content"] for m in shrunk if m["role"] == "tool"][:2] == [ELIDED_TOOL_RESULT] * 2
    assert removed == len(earlier) + 2


def test_context_overflow_is_recognised_and_never_retried_blindly():
    body = json.dumps({"error": {"message": "This model's maximum context length is 131072 tokens.",
                                 "type": "BadRequestError", "code": 400}})
    assert error_signals(body)[0] == "context_length_exceeded"
    anthropic = json.dumps({"error": {"type": "invalid_request_error",
                                      "message": "prompt is too long: 210000 tokens > 200000 maximum"}})
    assert error_signals(anthropic)[0] == "context_length_exceeded"
    # NVIDIA NIM / vLLM, measured 2026-10-08 (docs/evidence/continuity-canary-2026-10-08):
    # the prompt is subtracted from the window and the negative remainder rejected.
    nim = json.dumps({"error": {"message": "max_tokens must be at least 1, got -50994. "
                                "(parameter=max_tokens, value=-50994)", "type": "BadRequestError",
                                "param": "max_tokens", "code": 400}})
    assert error_signals(nim)[0] == "context_length_exceeded"
    zero = json.dumps({"error": {"message": "max_tokens must be at least 1, got 0.", "code": 400}})
    assert error_signals(zero)[0] is None                         # a real parameter error stays REQUEST
    error = StreamError("provider returned HTTP 400", status=400, provider_code="context_length_exceeded")
    assert classify_provider_error(error)["error_kind"] == "CONTEXT"
    assert classify_provider_error(StreamError("x", status=413))["error_kind"] == "CONTEXT"
    assert not plan_recovery(error, 1).retry                     # ADR 0008 never re-sends it as is


# ── The chat turn ─────────────────────────────────────────────────────
@pytest.fixture
def chat(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")

    async def no_wait(delay):
        return None

    monkeypatch.setattr(continuity_recovery, "wait_fixed", no_wait)
    return root


def run_app(scenario):
    async def main():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(main())


def shown(app):
    from isycode.tui import plain_text
    from isycode.tui_widgets import ChatArea
    parts = []
    for widget in app.query_one(ChatArea).walk_children():
        try:
            parts.append(plain_text(widget))
        except Exception:
            pass
    return "\n".join(parts)


def is_summary_request(messages):
    return str(messages[0].get("content", "")).startswith("Summarize the conversation")


def test_a_smaller_model_gets_a_capsule_and_no_conversation_leaves_for_another_provider(
        chat, monkeypatch, capsys):
    record_model_metadata("openai", "gpt-6-luna", {"context_length": 16_000})   # 24k chars
    save_model_slot("small", "nvidia", "small-model")          # another provider: never used here
    requests = []

    async def complete(provider, messages, **kwargs):
        requests.append((provider.name, list(messages)))
        return {"text": "ok", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        app._history = conversation(20)
        app._tool_history = list(NOTES)
        await app._run_chat("Continue with the parser")
        assert [name for name, _ in requests] == ["openai"]     # no summary sent to nvidia
        sent = requests[0][1]
        capsules = [message for message in sent if is_capsule(message)]
        assert len(capsules) == 1 and "request-0" in capsules[0]["content"]
        assert "request-0 " not in " ".join(str(m.get("content")) for m in sent if m["role"] == "user")
        assert not any(str(m.get("content", "")).startswith("Untrusted historical tool results")
                       for m in sent)
        assert total_chars([m for m in sent if m["role"] != "system" or is_capsule(m)]) <= 24_000
        assert sent[-1]["content"] == "Continue with the parser"
        assert "Context capsule · " in shown(app)
        assert len(app._history) == 42                           # the conversation itself is untouched

    with capsys.disabled():
        run_app(scenario)


def test_the_small_slot_on_the_same_provider_writes_the_narrative_notes(chat, monkeypatch, capsys):
    record_model_metadata("openai", "gpt-6-luna", {"context_length": 16_000})
    save_model_slot("small", "openai", "gpt-6-mini")
    requests = []

    async def complete(provider, messages, **kwargs):
        requests.append((provider.model, list(messages)))
        if is_summary_request(messages):
            return {"text": "NARRATIVE: the user is fixing the parser.", "tool_calls": [],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return {"text": "ok", "tool_calls": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        app._history = conversation(20)
        await app._run_chat("Continue")
        assert [model for model, _ in requests] == ["gpt-6-mini", "gpt-6-luna"]
        assert "NARRATIVE" in json.dumps(requests[1][1])
        assert app._conversation_summary.startswith("NARRATIVE")

    with capsys.disabled():
        run_app(scenario)


def test_a_too_long_rejection_is_capsuled_and_sent_once_more_without_repeating_tools(
        chat, monkeypatch, capsys):
    root = chat
    (root / "notes.txt").write_text("tool-result-marker\n")
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            return {"text": "", "tool_calls": [{"id": "r1", "function": {
                "name": "workspace_read", "arguments": '{"path":"notes.txt"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        if len(calls) == 2:
            raise StreamError("provider returned HTTP 400", status=400,
                              provider_code="context_length_exceeded")
        return {"text": "Done.", "tool_calls": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        app._history = conversation(4, size=50)
        dispatched = []
        original = app._dispatch_chat_tool

        async def counting(call, *args, **kwargs):
            dispatched.append(call["id"])
            return await original(call, *args, **kwargs)

        app._dispatch_chat_tool = counting
        await app._run_chat("Read notes.txt")
        assert dispatched == ["r1"] and len(calls) == 3
        retried = calls[2]
        assert any(is_capsule(m) and "request-0" in m["content"] for m in retried)
        assert not any(str(m.get("content", "")).startswith("request-0") for m in retried)
        assert any(m.get("role") == "tool" and m.get("tool_call_id") == "r1" for m in retried)
        assert app._history[-1]["content"] == "Done."
        assert "request was larger than the model window" in shown(app)

    with capsys.disabled():
        run_app(scenario)


def test_a_second_too_long_rejection_stops_the_turn(chat, monkeypatch, capsys):
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        raise StreamError("provider returned HTTP 413", status=413)

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        from isycode.tui_composer import PromptArea
        await app._run_chat("Hello")
        assert len(calls) == 2                                   # one capsule re-send, no loop
        assert app.query_one(PromptArea).text == "Hello"

    with capsys.disabled():
        run_app(scenario)


def test_a_long_resumed_session_continues_through_the_capsule(chat, monkeypatch, capsys):
    record_model_metadata("openai", "gpt-6-luna", {"context_length": 16_000})
    requests = []

    async def complete(provider, messages, **kwargs):
        requests.append(list(messages))
        return {"text": "ok " + "w" * 2_000, "tool_calls": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    monkeypatch.setattr("isycode.tui_app_chat.model_slot", lambda slot: {"provider": "nvidia",
                                                                         "model": "small"})

    async def scenario_first(app, pilot):
        for index in range(14):
            await app._run_chat(f"request-{index} " + "u" * 2_000)
        sid.append(app._active_chat_session_id)

    async def scenario_resumed(app, pilot):
        await app._resume_chat_session(sid[0])
        assert len(app._history) == 28
        await app._run_chat("Where were we?")
        sent = requests[-1]
        assert any(is_capsule(m) and "request-0" in m["content"] for m in sent)
        assert sent[-1]["content"] == "Where were we?"

    sid = []
    with capsys.disabled():
        run_app(scenario_first)
        run_app(scenario_resumed)


def test_a_subagent_starts_with_the_capsule(chat, monkeypatch, capsys):
    from isycode.providers import save_provider_selection
    from isycode.subagent_screen import SubagentModelScreen
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "child-key-not-real")
    save_provider_selection("nvidia", "child-model")
    seen = []

    async def complete(provider, messages, **kwargs):
        seen.append(list(messages))
        return {"text": "Child done.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        app._history = [{"role": "user", "content": "We are migrating the parser to v2"},
                        {"role": "assistant", "content": "Understood."}]
        app._tool_history = list(NOTES)
        app._agent_tasks = [{"title": "Port parse()", "status": "in_progress"}]
        task = asyncio.create_task(app._run_subagent("Check the parser tests."))
        for _ in range(100):
            await pilot.pause(.01)
            if isinstance(app.screen, SubagentModelScreen):
                break
        await app.screen.ready.wait()
        await pilot.pause(.1)
        await pilot.click("#child-launch")
        result = await asyncio.wait_for(task, 10)
        assert result["status"] == "completed"
        capsules = [m["content"] for m in seen[0] if is_capsule(m)]
        assert len(capsules) == 1 and len(capsules[0]) <= SUBAGENT_CAPSULE_CHARS
        assert "migrating the parser to v2" in capsules[0] and "Port parse()" in capsules[0]
        assert "ran · pytest -q · exit 1" in capsules[0]
        assert seen[0][-1] == {"role": "user", "content": "Check the parser tests."}

    with capsys.disabled():
        run_app(scenario)
