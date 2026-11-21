import asyncio
import json
from pathlib import Path

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.workspace_config_owner import WorkspaceConfigOwner
from isycode.approvals import ActionApprovalStore
from isycode.tui import TUIApp
from isycode.workspace_authority import WorkspaceAuthority


def test_session_context_survives_cancel_and_model_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.chdir(tmp_path)
    captured_turns: list[list[dict]] = []
    call_index = {"n": 0}

    async def fake_provider_complete(*args, **kwargs):
        call_index["n"] += 1
        msgs = kwargs.get("messages") if "messages" in kwargs else (args[1] if len(args) > 1 else [])
        captured_turns.append([dict(m) for m in msgs])
        if call_index["n"] == 1:
            kwargs["on_chunk"]("reasoning", "Thinking about isyco git/ project layout")
            raise asyncio.CancelledError()
        kwargs["on_chunk"]("content", "Continuing with your isyco git/ request.")
        return {"text": "Continuing with your isyco git/ request.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", fake_provider_complete)

    async def scenario():
        app = TUIApp(initial_mode="flow")
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            ctx_file = app._session_context_file()
            initial_path = ctx_file.path

            try:
                await app._run_chat("Hola me ayudas con un proyecto en isyco git/ :p")
            except asyncio.CancelledError:
                pass

            assert ctx_file.path == initial_path
            assert ctx_file.path.exists()
            from isycode.tui import PromptArea
            assert app.query_one(PromptArea).text == ""
            assert app._navigate_prompt_history(-1, "") == "Hola me ayudas con un proyecto en isyco git/ :p"
            raw_after_cancel = ctx_file.path.read_text(encoding="utf-8")
            assert "Hola me ayudas con un proyecto en isyco git/ :p" in raw_after_cancel
            assert "Thinking about isyco git/ project layout" in raw_after_cancel
            assert "stopped_by_user" in raw_after_cancel

            # Switch model mid-session (e.g. nvidia -> openrouter)
            monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-2")
            app._select_provider("openrouter")
            assert app._session_context_file().path == initial_path
            assert "[Model switched]" in initial_path.read_text(encoding="utf-8")

            # Follow-up turn receives the preserved prior turn + reasoning + canonical path
            await app._run_chat("continua")
            assert len(captured_turns) == 2
            second_messages = captured_turns[1]
            combined = "\n".join(str(m.get("content", "")) for m in second_messages)
            assert str(initial_path) in combined
            assert "Hola me ayudas con un proyecto en isyco git/ :p" in combined
            assert "Thinking about isyco git/ project layout" in combined
            assert "[Model switched]" in combined

            # Flow workspace_read can directly inspect the canonical session file
            owner = LocalWorkspaceReadOwner(tmp_path, WorkspaceAuthority(tmp_path))
            outcome = owner.execute("workspace.files.read", {"path": str(initial_path)})
            assert outcome.decision == "ALLOW"
            assert "Hola me ayudas con un proyecto en isyco git/ :p" in outcome.text

            # Manual user edit to the canonical file is picked up on the following turn
            with initial_path.open("a", encoding="utf-8") as handle:
                handle.write("\n- manual_note: focus on /tmp/custom-repo\n")
            await app._run_chat("usa la nota manual")
            assert len(captured_turns) == 3
            third_combined = "\n".join(str(m.get("content", "")) for m in captured_turns[2])
            assert "manual_note: focus on /tmp/custom-repo" in third_combined

    asyncio.run(scenario())


def test_flow_workspace_config_owner_reads_home_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    ws = tmp_path / "repo"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    (ws / ".isyroot").write_text("", encoding="utf-8")
    (ws / ".isycode").mkdir()
    (ws / ".isycode" / "config.json").write_text(
        json.dumps({"roots": [str(outside)]}), encoding="utf-8"
    )
    authority = WorkspaceAuthority(ws)
    authority.set_mode("flow")
    config_owner = WorkspaceConfigOwner(ws, authority, ActionApprovalStore())
    result, error = config_owner.read_config()
    assert error == ""
    assert result is not None


def test_flow_chat_omits_context_access_and_folder_enum(monkeypatch, tmp_path):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.chdir(tmp_path)
    seen = {}

    async def fake_provider_complete(*args, **kwargs):
        seen["messages"] = kwargs.get("messages") if "messages" in kwargs else (args[1] if len(args) > 1 else [])
        seen["tools"] = kwargs.get("tools") or []
        kwargs["on_chunk"]("content", "Listo.")
        return {"text": "Listo.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", fake_provider_complete)

    async def scenario():
        app = TUIApp(initial_mode="flow")
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            await app._run_chat("revisa mis carpetas")

    asyncio.run(scenario())
    tool_names = [t.get("function", {}).get("name") for t in seen["tools"]]
    assert "request_context_access" not in tool_names
    for tool in seen["tools"]:
        props = tool.get("function", {}).get("parameters", {}).get("properties", {})
        assert "folder" not in props
    sys_prompt = seen["messages"][0]["content"]
    assert "User-selected folder metadata" not in sys_prompt
    assert "Session context file:" in sys_prompt


def test_isymem_context_and_slash_command(monkeypatch, tmp_path):
    mem_dir = tmp_path / "isymem-bank"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text(
        "## Reglas\n- [No hardcoded results](no-hardcoded.md) — derive counts from runs\n\n"
        "## Proyectos\n- [ISyCode](hub-isycode.md) — Live session context & Flow mode\n",
        encoding="utf-8",
    )
    (mem_dir / "hub-isycode.md").write_text(
        "# ISyCode\n- @todo#a1b2 #isycode 2026-11-18: Polish Model picker for GUS\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ISYMEM_DIR", str(mem_dir))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.chdir(tmp_path)
    seen = {}

    async def fake_provider_complete(*args, **kwargs):
        seen["messages"] = kwargs.get("messages") if "messages" in kwargs else args[1]
        kwargs["on_chunk"]("content", "OK.")
        return {"text": "OK.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", fake_provider_complete)

    async def scenario():
        app = TUIApp(initial_mode="flow")
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            assert any(name == "isymem" for name, _ in app._plugins.command_items())
            await app._run_chat("revisa los pendientes de isycode")

    asyncio.run(scenario())
    joined = "\n".join(str(m.get("content", "")) for m in seen["messages"])
    assert "Shared Multi-Harness Memory (`isymem`" in joined
    assert str(mem_dir.resolve()) in joined
    assert "No hardcoded results" in joined
    assert "Polish Model picker for GUS" in joined
