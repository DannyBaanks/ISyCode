"""M9 adversarial matrix: hostile output, disk full, network down, slow provider.

Each case uses the real owners, Authority, Sentinel and journal. The network
cases use the real provider transport against a socket on 127.0.0.1 that this
test controls (refusing, or accepting and stalling); nothing leaves the host.
Journal/ledger corruption and crash recovery are covered by
test_action_audit*.py and test_effect_ledger.py and are not repeated here.
"""
import asyncio
import errno
import json
import os
import socket
import time

import pytest

from isycode import continuity_recovery
from isycode.action_audit import ActionAuditJournal
from isycode.approvals import ActionApprovalStore
from isycode.terminal_safety import strip_controls
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner
from test_daily_tui import configure

HOSTILE = ("ok \x1b[2J\x1b[H\x1b]0;PWNED-TITLE\x07\x1b]52;c;cHdu\x07"
           " \x9b31m tail \x1b[31mred\x1b[0m end")
# Sequences, not their printable residue: "]0;PWNED" left as plain text is harmless.
ATTACKS = ("\x1b[2J", "\x1b[H", "\x1b]0;", "\x1b]52;", "\x9b", "\x07")


def terminal_bytes(app) -> str:
    """Exactly what Textual would write to the terminal for a full repaint."""
    return app.screen._compositor.render_update(full=True).render_segments(app.console)


def run(scenario, size=(120, 40)):
    from isycode.tui import TUIApp

    async def main():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(main())


# ── Hostile output / ANSI injection ────────────────────────────────────
def test_control_characters_are_removed_and_styles_kept():
    from rich.console import Console
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip
    import isycode.tui  # noqa: F401  (installs the filter)
    out = Strip([Segment(HOSTILE, Style(bold=True))]).render(Console(color_system="truecolor"))
    assert not any(attack in out for attack in ATTACKS)
    assert "ok" in out and "tail" in out and "end" in out
    assert "\x1b[1m" in out                                       # Textual's own styling stays
    assert strip_controls("a\x00b\x7fc\x85d\x1be") == "abcde"


def test_a_hostile_model_reply_cannot_drive_the_terminal(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def complete(provider, messages, **kwargs):
        kwargs["on_chunk"]("content", HOSTILE)
        return {"text": HOSTILE, "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario(app, pilot):
        await app._run_chat("hi")
        await pilot.pause()
        out = terminal_bytes(app)
        assert "tail" in out and "end" in out                      # the text is still shown
        assert not any(attack in out for attack in ATTACKS)        # its control codes are not
        assert app._history[-1]["content"] == HOSTILE              # data itself is not rewritten

    with capsys.disabled():
        run(scenario)


def test_a_hostile_file_shown_in_the_preview_cannot_drive_the_terminal(tmp_path, monkeypatch, capsys):
    # Regression guard: Static(str) goes through Textual Content, which already drops
    # control codes; the chat (Rich Markdown/Text) did not until terminal_safety.
    root = configure(tmp_path, monkeypatch)
    (root / "evil.txt").write_text("SEEN " + HOSTILE + "\n")   # the preview pane is narrow

    async def scenario(app, pilot):
        app._set_rail_view("files")
        await app._preview_file(str(app._workspace_root / "evil.txt"))
        await pilot.pause()
        out = terminal_bytes(app)
        assert "SEEN" in out                                        # the file really is on screen
        assert not any(attack in out for attack in ATTACKS)

    with capsys.disabled():
        run(scenario, size=(160, 44))


# ── Disk full ──────────────────────────────────────────────────────────
REAL_WRITE = os.write


def no_space_under(prefix):
    """os.write that fails with ENOSPC only for files under ``prefix``."""
    prefix = str(prefix)

    def write(fd, data):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = ""
        if target.startswith(prefix):
            raise OSError(errno.ENOSPC, "No space left on device")
        return REAL_WRITE(fd, data)
    return write


needs_proc = pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs /proc fd links")


@pytest.fixture
def writer(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "w"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    authority = WorkspaceAuthority(root)
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[str(root.resolve())])
    approvals = ActionApprovalStore()
    return WorkspaceWriteOwner(root, authority, approvals), approvals, root.resolve(), state.resolve()


@needs_proc
@pytest.mark.parametrize("where, verdict", [
    ("workspace", "ERROR"),          # the file itself
    ("action-audit", "DENY"),        # the journal: authorization not durable
    ("effect-ledger", "DENY"),       # the ledger: no budget record, no change
])
def test_a_full_disk_never_changes_the_file_and_never_leaks_a_raw_error(writer, monkeypatch, where, verdict):
    owner, approvals, root, state = writer
    preview = owner.preview_edit("a.py", "x = 1", "x = 2")
    (state / where).mkdir(parents=True, exist_ok=True)
    prefix = root if where == "workspace" else state / where
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", no_space_under(prefix))
        outcome = owner.apply(preview, approvals.issue(preview.request))  # must not raise
    assert outcome.decision == verdict and "space" in outcome.reason.lower()
    assert (root / "a.py").read_text() == "x = 1\n"
    assert sorted(path.name for path in root.iterdir()) == ["a.py"]    # no temp file left
    if where != "effect-ledger":
        assert ActionAuditJournal(root).verify().status == "PASS"
    # Space comes back: the same change goes through, so no lock or state was left behind.
    again = owner.preview_edit("a.py", "x = 1", "x = 2")
    assert owner.apply(again, approvals.issue(again.request)).decision == "ALLOW"
    assert (root / "a.py").read_text() == "x = 2\n"


def test_a_short_write_never_truncates_the_effect_ledger(writer, monkeypatch):
    owner, approvals, root, state = writer

    def short(fd, data):                     # the kernel may accept only part of a write
        return REAL_WRITE(fd, bytes(data[:7]))

    preview = owner.preview_edit("a.py", "x = 1", "x = 2")
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", short)
        assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    for ledger in (state / "effect-ledger").glob("*.json"):
        json.loads(ledger.read_text())       # complete, parseable state


@needs_proc
def test_with_the_state_disk_full_the_chat_denies_explains_and_keeps_the_prompt(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / "a.py").write_text("x = 1\n")
    calls = []

    async def complete(provider, messages, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {"text": "", "tool_calls": [{"id": "e1", "type": "function", "function": {
                "name": "workspace_edit", "arguments": json.dumps(
                    {"path": "a.py", "old_text": "x = 1", "new_text": "x = 2"})}}]}
        return {"text": "Done.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    from isycode.tui import WriteApprovalScreen
    from isycode.tui_composer import PromptArea

    async def scenario(app, pilot):
        task = asyncio.create_task(app._run_chat("set x to 2"))
        for _ in range(100):
            await pilot.pause(0.05)
            if isinstance(app.screen, WriteApprovalScreen):
                break
        with monkeypatch.context() as patch:
            patch.setattr(os, "write", no_space_under((tmp_path / "state").resolve()))
            await pilot.press("y")
            await asyncio.wait_for(task, 10)
        from isycode.tui import plain_text
        from isycode.tui_widgets import ChatArea
        shown = "\n".join(plain_text(w) for w in app.query_one(ChatArea).walk_children()
                          if hasattr(w, "render"))
        assert (root / "a.py").read_text() == "x = 1\n"
        assert "No space left on device" in shown and "nothing was changed" in shown
        assert "no further request was sent" in shown              # the journal stops the next call
        assert len(calls) == 1
        assert app.query_one(PromptArea).text == "set x to 2"      # nothing the user typed is lost

    with capsys.disabled():
        run(scenario)


# ── Network down and slow provider (real transport, local socket) ─────
def local_provider(tmp_path, monkeypatch, port):
    from isycode import egress
    real_ips = egress._ips
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr("isycode.egress._ips", real_ips)            # resolve for real: loopback only
    monkeypatch.setenv("ISYCODE_PROVIDER", "llamacpp")
    monkeypatch.setenv("ISYCODE_MODEL", "local-test")
    monkeypatch.setenv("ISYCODE_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]          # closed again when the block ends


def test_network_down_is_retried_briefly_then_stops_without_changing_authority(tmp_path, monkeypatch, capsys):
    port = closed_port()
    local_provider(tmp_path, monkeypatch, port)
    waits = []

    async def no_wait(delay):
        waits.append(delay)

    monkeypatch.setattr(continuity_recovery, "wait_fixed", no_wait)
    from isycode.tui_composer import PromptArea

    async def scenario(app, pilot):
        before = WorkspaceAuthority(app._workspace_root).policy()
        await app._run_chat("hello")
        await pilot.pause()
        from isycode.tui import plain_text
        from isycode.tui_widgets import ChatArea
        shown = "\n".join(plain_text(w) for w in app.query_one(ChatArea).walk_children()
                          if hasattr(w, "render"))
        assert waits == [continuity_recovery.POLICIES["NETWORK"].delay_s] * 3
        assert "Recovery stopped after 3 automatic attempts" in shown
        assert app.query_one(PromptArea).text == "hello"
        assert WorkspaceAuthority(app._workspace_root).policy() == before

    with capsys.disabled():
        run(scenario)


def test_a_stalled_provider_is_cancelled_quickly_and_its_socket_closed(tmp_path, monkeypatch, capsys):
    events = {"closed": None}

    async def scenario(app, pilot):
        accepted = asyncio.Event()

        async def stall(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")
            await writer.drain()
            accepted.set()
            await reader.read()                  # returns b"" once the client hangs up
            events["closed"] = time.monotonic()

        server = await asyncio.start_server(stall, "127.0.0.1", port)
        try:
            turn = asyncio.create_task(app._run_chat("hello"))
            await asyncio.wait_for(accepted.wait(), 10)
            pressed = time.monotonic()
            app.action_escape_to_chat()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(turn, 2)
            stopped = time.monotonic() - pressed
            for _ in range(40):
                if events["closed"]:
                    break
                await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()
        assert stopped <= 0.25                                       # G9-03 UI acknowledgement
        assert events["closed"] is not None and events["closed"] - pressed <= 2   # socket gone

    port = closed_port()
    local_provider(tmp_path, monkeypatch, port)
    with capsys.disabled():
        run(scenario)
