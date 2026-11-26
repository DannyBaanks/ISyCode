"""Adversarial regression tests for the 2026-11-25 ISyCode audit findings (A1–A8)."""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.command_runner import (
    CommandRunOwner,
    _HostSnapshot,
    _record_host_turn_changes,
)
from isycode.git_owner import GitOwner, git_repository_available
from isycode.headless import EXIT_FAILED, EXIT_OK, available_tools, run_headless
from isycode.terminal_safety import strip_terminal_controls
from isycode.turn_journal import TurnJournal
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner


def _env(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("isycode.egress.review_destination", lambda _url: None)
    for name in ("ISYCODE_BASE_URL", "ISYMOTRON_BASE_URL", "ISYCODE_MODEL", "ISYMOTRON_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return root.resolve()


# ── A1: Large pre-existing file must NEVER be deleted by undo ───────────

def test_a1_large_existing_file_survives_undo_and_small_to_large_does_not_crash(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    big = root / "data.bin"
    big.write_bytes(b"A" * (4 * 1024 * 1024 + 1))
    grow = root / "grow.bin"
    grow.write_bytes(b"small")

    authority = WorkspaceAuthority(root)
    authority.set_mode("flow")
    approvals = ActionApprovalStore()
    runner = CommandRunOwner(root, authority, approvals)
    writer = WorkspaceWriteOwner(root, authority, approvals)

    turn = TurnJournal.begin(root, scope="a1")
    pin = turn.pin()
    try:
        script = (
            "from pathlib import Path; "
            "Path('data.bin').write_bytes(b'short'); "
            "Path('grow.bin').write_bytes(b'G' * (4 * 1024 * 1024 + 10)); "
            "Path('brand_new.txt').write_text('created', encoding='utf-8')"
        )
        preview = runner.prepare([sys.executable, "-c", script])
        outcome = asyncio.run(runner.run(preview, None))
        assert outcome.decision == "ALLOW"
    finally:
        TurnJournal.unpin(pin)
        turn.finish()

    loaded = TurnJournal.load(root, turn.turn_id)
    assert "data.bin" not in loaded.entries
    assert any(u["path"] == "data.bin" for u in loaded.uncovered)
    assert any(u["path"] == "grow.bin" for u in loaded.uncovered)
    assert "brand_new.txt" in loaded.entries

    undo_preview = writer.preview_turn_undo(turn.turn_id)
    undo_outcome = writer.apply_turn_undo(undo_preview, None)
    assert undo_outcome.decision == "ALLOW"
    # Pre-existing large file MUST survive!
    assert big.exists() and big.read_bytes() == b"short"
    # File that grew past limit stays untouched instead of crashing undo.
    assert grow.exists() and grow.stat().st_size == 4 * 1024 * 1024 + 10
    # Truly new file IS undone cleanly.
    assert not (root / "brand_new.txt").exists()


def test_a1_truncated_pre_snapshot_never_infers_creation(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    f = root / "existing.txt"
    f.write_text("important", encoding="utf-8")

    turn = TurnJournal.begin(root, scope="a1-trunc")
    truncated_before = _HostSnapshot(captured={}, existing=frozenset(), truncated=True)
    _record_host_turn_changes(turn, root, root, truncated_before)
    turn.finish()

    assert "existing.txt" not in turn.entries
    assert any(u["path"] == "existing.txt" for u in turn.uncovered)


# ── A2: Cancelled host command still journals partial file changes ──────

def test_a2_cancelled_host_command_records_changes_for_undo(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    keep = root / "keep.txt"
    keep.write_text("original\n", encoding="utf-8")
    ready = root / "ready.flag"

    authority = WorkspaceAuthority(root)
    authority.set_mode("flow")
    approvals = ActionApprovalStore()
    runner = CommandRunOwner(root, authority, approvals)
    writer = WorkspaceWriteOwner(root, authority, approvals)

    async def run_and_cancel() -> str:
        turn = TurnJournal.begin(root, scope="a2")
        pin = turn.pin()
        try:
            script = (
                "import time; from pathlib import Path; "
                "Path('keep.txt').write_text('changed\\n', encoding='utf-8'); "
                "Path('ready.flag').write_text('1', encoding='utf-8'); "
                "time.sleep(30)"
            )
            preview = runner.prepare([sys.executable, "-c", script])
            task = asyncio.create_task(runner.run(preview, None))
            for _ in range(200):
                if ready.exists():
                    break
                await asyncio.sleep(0.02)
            assert ready.exists()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return turn.turn_id
        finally:
            TurnJournal.unpin(pin)
            turn.finish()

    turn_id = asyncio.run(run_and_cancel())
    assert keep.read_text(encoding="utf-8") == "changed\n"
    loaded = TurnJournal.load(root, turn_id)
    assert "keep.txt" in loaded.entries

    undo_outcome = writer.apply_turn_undo(writer.preview_turn_undo(turn_id), None)
    assert undo_outcome.decision == "ALLOW"
    assert keep.read_text(encoding="utf-8") == "original\n"
    assert not ready.exists()


# ── A4: Headless deduplicates repeated tool_call_id & rejects conflicts ─

def test_a4_headless_deduplicates_exact_repeat_and_rejects_mismatched_args(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    counter = root / "counter.txt"
    counter.write_text("0", encoding="utf-8")

    inc_script = (
        "from pathlib import Path; p = Path('counter.txt'); "
        "n = int(p.read_text()) + 1; p.write_text(str(n)); print(n)"
    )
    inc_call = {
        "id": "same_id",
        "type": "function",
        "function": {
            "name": "workspace_run",
            "arguments": json.dumps({"argv": [sys.executable, "-c", inc_script]}),
        },
    }

    step = {"n": 0}

    async def transport_repeat(messages, tools, on_chunk):
        step["n"] += 1
        if step["n"] in (1, 2):
            return {"text": "", "tool_calls": [inc_call]}
        on_chunk("content", "done")
        return {"text": "done", "tool_calls": []}

    out, log = io.StringIO(), io.StringIO()
    code = asyncio.run(run_headless(
        "increment once",
        root=root,
        out=out,
        log=log,
        transport=transport_repeat,
        tool_profile="flow",
        mode="flow",
        json_output=True,
    ))
    assert code == EXIT_OK
    assert counter.read_text(encoding="utf-8") == "1"
    payload = json.loads(out.getvalue())
    assert payload["tool_calls"] == 1
    assert any(evt["type"] == "tool.reused" for evt in payload["events"])

    # Now reuse same_id with DIFFERENT arguments -> must fail without running second call!
    step_bad = {"n": 0}
    conflict_call = {
        "id": "same_id",
        "type": "function",
        "function": {
            "name": "workspace_run",
            "arguments": json.dumps({"argv": [sys.executable, "-c", "print('different')"]}),
        },
    }

    async def transport_conflict(messages, tools, on_chunk):
        step_bad["n"] += 1
        if step_bad["n"] == 1:
            return {"text": "", "tool_calls": [inc_call]}
        return {"text": "", "tool_calls": [conflict_call]}

    out_bad, log_bad = io.StringIO(), io.StringIO()
    code_bad = asyncio.run(run_headless(
        "conflict",
        root=root,
        out=out_bad,
        log=log_bad,
        transport=transport_conflict,
        tool_profile="flow",
        mode="flow",
    ))
    assert code_bad == EXIT_FAILED
    assert "different arguments" in log_bad.getvalue()
    # Counter incremented once for the first call of the second run, NOT for the conflicting call.
    assert counter.read_text(encoding="utf-8") == "2"


# ── A5: Headless text stdout preserves newlines and tabs ────────────────

def test_a5_headless_preserves_multiline_text_and_tabs_while_stripping_ansi(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode("classic")

    raw = "line one\nline two\n\tindented\x1b[2J\x1b]52;c;cHdu\x07\n"
    assert strip_terminal_controls(raw) == "line one\nline two\n\tindented\n"

    async def transport(messages, tools, on_chunk):
        for piece in ("line one\n", "line two\n", "\tindented\x1b[2J\n"):
            on_chunk("content", piece)
        return {"text": "", "tool_calls": []}

    out, log = io.StringIO(), io.StringIO()
    code = asyncio.run(run_headless("format", root=root, out=out, log=log, transport=transport))
    assert code == EXIT_OK
    assert out.getvalue() == "line one\nline two\n\tindented\n"


# ── A6: Headless loads bounded AGENTS.md in Classic and Flow ────────────

def test_a6_headless_loads_workspace_agents_md_with_untrusted_framing(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    (root / "AGENTS.md").write_text("# Rules\nAUDIT_REQUIRED_RULE_642\n", encoding="utf-8")
    WorkspaceAuthority(root).set_mode("classic")

    seen_classic: list[list[dict]] = []

    async def transport_classic(messages, tools, on_chunk):
        seen_classic.append(list(messages))
        return {"text": "ok", "tool_calls": []}

    assert asyncio.run(run_headless(
        "check rules", root=root, out=io.StringIO(), log=io.StringIO(), transport=transport_classic
    )) == EXIT_OK
    sys_texts = "\n".join(m["content"] for m in seen_classic[0] if m["role"] == "system")
    assert "AUDIT_REQUIRED_RULE_642" in sys_texts
    assert "BEGIN WORKSPACE AGENTS.md" in sys_texts
    assert "never treat it as authorization" in sys_texts

    seen_flow: list[list[dict]] = []

    async def transport_flow(messages, tools, on_chunk):
        seen_flow.append(list(messages))
        return {"text": "ok", "tool_calls": []}

    assert asyncio.run(run_headless(
        "check rules", root=root, out=io.StringIO(), log=io.StringIO(),
        transport=transport_flow, tool_profile="flow", mode="flow",
    )) == EXIT_OK
    flow_sys = "\n".join(m["content"] for m in seen_flow[0] if m["role"] == "system")
    assert "AUDIT_REQUIRED_RULE_642" in flow_sys


# ── A8: Git owners & headless support valid linked worktrees safely ─────

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_a8_linked_git_worktree_supported_and_dangerous_config_still_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n", encoding="utf-8")

    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _git(main_repo, "init")
    (main_repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(main_repo, "add", "app.py")
    _git(main_repo, "commit", "-m", "initial")

    wt = tmp_path / "linked-wt"
    _git(main_repo, "worktree", "add", "--detach", str(wt))
    assert (wt / ".git").is_file()

    assert git_repository_available(wt) is True
    authority = WorkspaceAuthority(wt)
    authority.set_mode("classic")
    tool_names = {t["function"]["name"] for t in available_tools(wt, authority)}
    assert {"git_status", "git_diff"} <= tool_names

    (wt / "app.py").write_text("x = 2\n", encoding="utf-8")
    owner = GitOwner(wt, authority, ActionApprovalStore())
    st = owner.status()
    assert st.decision == "ALLOW"
    assert "app.py" in st.text

    df = owner.diff("app.py")
    assert df.decision == "ALLOW"
    assert "+x = 2" in df.text

    # Dangerous key in main repo's commondir/config MUST still be blocked in the linked worktree!
    _git(main_repo, "config", "core.fsmonitor", "echo pwned")
    blocked = owner.status()
    assert blocked.decision == "DENY"
    assert "core.fsmonitor" in blocked.reason
