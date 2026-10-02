"""M6: cancel in-flight work and reconcile a retry without a second effect.

Interrupt points and the state the tests observe:

| point | final state |
| stream read | task cancelled, client socket closed, no tool call returned |
| staging child and grandchild | no live host /proc entry still carries that work's marker |
| promotion before the next file | earlier file restored or UNCERTAIN, later file untouched |
| lost response after an effect | one transport or one ledger charge, else UNCERTAIN |
| owner restarted | the same receipt or reservation settles once |
| truncated tool arguments | tool_calls empty; a new draft stays; history order stays |
| connect retry | at most 3 attempts, cancel stops the rest, grants unchanged |
"""
import asyncio
import json
import os
import random
import secrets
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_executable
from isycode.effect_ledger import CrashInjected, EffectCost, EffectLedger, LedgerDenied
from isycode.publish import PublishOwner
from isycode.staging import (
    PromotionCancelled, cleanup_staging, measure_changes, prepare_staging, promote_accounted,
)
from isycode.streaming import StreamError, async_stream_complete
from isycode.turn_control import (
    OperationJournal, RetryCancelled, TransportRetry, tool_arguments_complete,
)
from isycode.workspace_authority import WorkspaceAuthority

REMOTE = "https://github.com/example/repo.git"
DIGEST = "ab" * 32
OTHER = "cd" * 32


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    return root


def _isolate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})


def _live_pids(marker: str) -> list[int]:
    needle = marker.encode()
    me = os.getpid()
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == me:
            continue
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
            state = stat.rsplit(")", 1)[-1].split()[0]
            if state == "Z":
                continue
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            continue
        if needle in cmdline:
            found.append(pid)
    return found


def test_g6_01_cancel_during_stream_closes_the_socket():
    closed = asyncio.Event()
    accepted = asyncio.Event()
    returned = []

    async def scenario():
        async def handler(reader, writer):
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                accepted.set()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\n")
                writer.write(b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                             b'"function":{"name":"workspace_write","arguments":"{\\"path\\":"}}]}}]}\n\n')
                await writer.drain()
                await reader.read()
            finally:
                writer.close()
                closed.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            task = asyncio.create_task(async_stream_complete(
                f"http://127.0.0.1:{port}/v1", "", "fixture", [], timeout_s=5))
            await asyncio.wait_for(accepted.wait(), 2)
            task.cancel()
            result = await asyncio.gather(task, return_exceptions=True)
            returned.extend(result)
            await asyncio.wait_for(closed.wait(), 2)

    asyncio.run(scenario())
    assert closed.is_set()
    assert len(returned) == 1 and isinstance(returned[0], asyncio.CancelledError)


def test_g6_01_cancel_during_staging_kills_child_and_grandchild(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    sandbox = sandbox_executable()
    assert sandbox is not None
    root = _root(tmp_path)
    marker = "isycode-g6-" + secrets.token_hex(8)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
    approvals = ActionApprovalStore()
    owner = CommandRunOwner(root, authority, approvals)
    script = (
        "import os, time\n"
        f"marker = {marker!r}\n"
        "if os.fork() == 0:\n"
        "    os.fork()\n"
        "time.sleep(60)\n"
    )
    preview = owner.prepare(["python3", "-c", script], timeout_s=20)

    async def scenario():
        task = asyncio.create_task(owner.run_staged(preview, approvals.issue(preview.request)))
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline and len(_live_pids(marker)) < 3:
            await asyncio.sleep(0.05)
        seen = _live_pids(marker)
        task.cancel()
        outcome = await asyncio.gather(task, return_exceptions=True)
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline and _live_pids(marker):
            await asyncio.sleep(0.05)
        return seen, outcome, _live_pids(marker)

    seen, outcome, left = asyncio.run(scenario())
    assert len(seen) >= 3
    assert isinstance(outcome[0], asyncio.CancelledError)
    assert left == []
    assert {path.name for path in root.iterdir()} == {".isyroot"}


def test_g6_01_cancel_during_promotion_stops_later_files(tmp_path):
    root = _root(tmp_path)
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    operation_id = "12" * 32
    book = EffectLedger(root, state_directory=tmp_path / "ledger")
    journal = OperationJournal(root, state_directory=tmp_path / "operations")
    staging = prepare_staging(root)
    try:
        (staging.root / "a.txt").write_text("A\n", encoding="utf-8")
        (staging.root / "b.txt").write_text("B\n", encoding="utf-8")

        def interrupt(step: str) -> None:
            if step == "before-apply:1":
                raise PromotionCancelled(step)

        with pytest.raises(PromotionCancelled):
            promote_accounted(staging, measure_changes(staging), ledger=book,
                              operation_id=operation_id, operations=journal, interrupt=interrupt)
        assert (root / "a.txt").read_text(encoding="utf-8") == "a\n"
        assert (root / "b.txt").read_text(encoding="utf-8") == "b\n"
        assert book.status()["churn_bytes"] == 0
        before = book.status()["churn_bytes"]
        with pytest.raises(LedgerDenied) as blocked:
            promote_accounted(staging, measure_changes(staging), ledger=book,
                              operation_id=operation_id, operations=journal)
        assert blocked.value.effect_state == "uncertain"
        assert (root / "a.txt").read_text(encoding="utf-8") == "a\n"
        assert (root / "b.txt").read_text(encoding="utf-8") == "b\n"
        assert book.status()["churn_bytes"] == before
    finally:
        cleanup_staging(staging)


def test_g6_02_lost_publish_response_is_not_a_second_publish(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    root = _root(tmp_path)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("git.push", enabled=True, targets=[REMOTE])
    approvals = ActionApprovalStore()
    owner = PublishOwner(root, authority, approvals)
    calls = []

    def transport(remote, ref, digest):
        calls.append((remote, ref, digest))

    preview = owner.prepare(REMOTE, "main", DIGEST)
    owner.gate.persist_receipt = lambda request, receipt: False
    lost = owner.run(preview, approvals.issue(preview.request), transport)
    assert lost.decision == "NOT_VERIFIABLE"
    assert calls == [(REMOTE, "main", DIGEST)]
    restarted = PublishOwner(root, authority, ActionApprovalStore())
    again = restarted.run(preview, None, transport)
    assert again.decision == "UNCERTAIN"
    assert "lost" in again.reason
    assert calls == [(REMOTE, "main", DIGEST)]


def test_g6_02_a_committed_promotion_is_not_charged_twice(tmp_path):
    root = _root(tmp_path)
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    operation_id = "34" * 32
    state = tmp_path / "ledger"
    ops = tmp_path / "operations"
    book = EffectLedger(root, state_directory=state)
    journal = OperationJournal(root, state_directory=ops)
    staging = prepare_staging(root)
    try:
        (staging.root / "a.txt").write_text("A\n", encoding="utf-8")
        changes = measure_changes(staging)
        with pytest.raises(CrashInjected):
            promote_accounted(staging, changes, ledger=book, crash_at="after-commit",
                              operation_id=operation_id, operations=journal)
        charged = book.status()["churn_bytes"]
        assert charged > 0 and (root / "a.txt").read_text(encoding="utf-8") == "A\n"
        revived_book = EffectLedger(root, state_directory=state)
        revived_journal = OperationJournal(root, state_directory=ops)
        applied, _refused, info = promote_accounted(
            staging, changes, ledger=revived_book, operation_id=operation_id,
            operations=revived_journal)
        assert info["state"] == "committed" and info["reconciled"] is True
        assert applied == ["a.txt"]
        assert revived_book.status()["churn_bytes"] == charged
        assert (root / "a.txt").read_text(encoding="utf-8") == "A\n"
    finally:
        cleanup_staging(staging)


def test_g6_03_restart_keeps_an_open_reservation_and_one_charge(tmp_path):
    root = _root(tmp_path)
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    state = tmp_path / "ledger"
    operation_id = "56" * 32
    journal = OperationJournal(root, state_directory=tmp_path / "operations")
    staging = prepare_staging(root)
    try:
        (staging.root / "a.txt").write_text("A\n", encoding="utf-8")
        (staging.root / "b.txt").write_text("B\n", encoding="utf-8")
        book = EffectLedger(root, state_directory=state)
        with pytest.raises(CrashInjected):
            promote_accounted(staging, measure_changes(staging), ledger=book,
                              crash_at="after-apply:0", operation_id=operation_id, operations=journal)
        assert book.status()["open"] is True
        revived = EffectLedger(root, state_directory=state)
        assert revived.status()["open"] is True
        first = revived.reconcile()
        second = revived.reconcile()
        assert first in {"ROLLED_BACK", "UNCERTAIN", "COMMITTED"}
        assert second in {"IDLE", "UNCERTAIN"}
        charged = revived.status()["churn_bytes"]
        if revived.status()["uncertain"]:
            with pytest.raises(LedgerDenied):
                revived.reserve(EffectCost(("c.txt",), 0, 1))
        else:
            with pytest.raises(LedgerDenied):
                promote_accounted(staging, measure_changes(staging), ledger=revived,
                                  operation_id=operation_id,
                                  operations=OperationJournal(root, state_directory=tmp_path / "operations"))
        assert revived.status()["churn_bytes"] == charged
    finally:
        cleanup_staging(staging)


def _events(monkeypatch, events):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})

    async def scenario():
        async def handler(reader, writer):
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                body = "".join("data: " + (event if isinstance(event, str) else json.dumps(event))
                               + "\n\n" for event in events).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
                             + b"\r\n\r\n" + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await async_stream_complete(f"http://127.0.0.1:{port}/v1", "", "fixture", [],
                                               timeout_s=2)

    return asyncio.run(scenario())


def test_g6_04_truncated_tool_calls_are_not_executable(monkeypatch):
    assert tool_arguments_complete('{"path": "a"}') is True
    assert tool_arguments_complete('{"path":') is False
    hung = _events(monkeypatch, [{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_partial", "function": {"name": "workspace_write",
                                                        "arguments": '{"path":'}}]},
        "finish_reason": "tool_calls"}]}])
    assert hung["tool_calls"] == []
    done_but_cut = _events(monkeypatch, [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_cut", "function": {"name": "workspace_write",
                                                        "arguments": '{"path":'}}]},
            "finish_reason": "tool_calls"}]}, "[DONE]"])
    assert done_but_cut["tool_calls"] == []
    whole = _events(monkeypatch, [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_ok", "function": {"name": "workspace_write", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path": "a"}'}}]}, "finish_reason": "tool_calls"}]},
        "[DONE]"])
    assert whole["tool_calls"][0]["function"]["arguments"] == '{"path": "a"}'


def test_g6_04_retry_keeps_the_new_draft_and_transcript_order(tmp_path, monkeypatch, capsys):
    from isycode.tui import PromptArea, TUIApp
    from isycode.user_defaults import UserDefaultsStore
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("ISYCODE_MODEL", "gpt-6-luna")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic")
    authority = WorkspaceAuthority(project)
    authority.set_mode("classic")
    from isycode.workspace_trust import WorkspaceTrust
    WorkspaceTrust().decline(authority)

    async def idle(self):
        return None

    monkeypatch.setattr(TUIApp, "_refresh_openisy", idle)
    monkeypatch.setattr(TUIApp, "_check_gateway_async", idle)
    monkeypatch.setattr(TUIApp, "_check_model", idle)
    started = asyncio.Event()

    async def slow(*args, **kwargs):
        kwargs["on_chunk"]("content", "partial")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("isycode.tui.provider_complete", slow)
    prior = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._history = list(prior)
            app._tool_history = [{"name": "workspace_read", "arguments": "{}", "result": "old note"}]
            task = asyncio.create_task(app._run_chat("original"))
            await asyncio.wait_for(started.wait(), 5)
            app.query_one(PromptArea).load_text("new draft")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert app.query_one(PromptArea).text == "new draft"
            assert app._history == prior
            assert app._tool_history == [{"name": "workspace_read", "arguments": "{}", "result": "old note"}]
            app._prepare_retry()
            assert app.query_one(PromptArea).text == "new draft"
            assert app._history == prior

    with capsys.disabled():
        asyncio.run(scenario())


def test_g6_05_python_310_tasks_have_no_cancelling_attribute(monkeypatch):
    class LegacyTask:
        def cancelled(self):
            return False

    monkeypatch.setattr(asyncio, "current_task", lambda: LegacyTask())
    TransportRetry._raise_if_cancelled(None)

    class CancellingTask:
        def cancelling(self):
            return 1

    monkeypatch.setattr(asyncio, "current_task", lambda: CancellingTask())
    with pytest.raises(asyncio.CancelledError):
        TransportRetry._raise_if_cancelled(None)


def test_g6_05_backoff_is_bounded_cancellable_and_does_not_change_authority(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        TransportRetry(max_attempts=5)
    retry = TransportRetry(max_attempts=3, base_delay_s=0.05, max_delay_s=0.2, rng=random.Random(1))
    for index in range(3):
        delay = retry.delay_for(index)
        cap = min(0.2, 0.05 * (2 ** index))
        assert cap * 0.5 <= delay <= cap

    async def bounds():
        waits = []

        async def sleeper(delay):
            waits.append(delay)

        attempts = {"n": 0}

        async def connect():
            attempts["n"] += 1
            raise ConnectionRefusedError("down")

        with pytest.raises(ConnectionRefusedError):
            await TransportRetry(max_attempts=3, sleeper=sleeper, rng=random.Random(2)).attempt(connect)
        assert attempts["n"] == 3 and len(waits) == 2
        assert all(item <= 0.2 for item in waits)

        cancelled = asyncio.Event()

        async def stop(delay):
            cancelled.set()

        attempts["n"] = 0
        with pytest.raises(RetryCancelled):
            await TransportRetry(max_attempts=4, sleeper=stop).attempt(connect, cancelled=cancelled)
        assert attempts["n"] == 1

        async def rejected():
            attempts["n"] += 1
            raise ValueError("not a connect failure")

        attempts["n"] = 0
        with pytest.raises(ValueError):
            await TransportRetry(max_attempts=3, sleeper=sleeper).attempt(rejected)
        assert attempts["n"] == 1

    asyncio.run(bounds())

    _isolate(monkeypatch, tmp_path)
    root = _root(tmp_path)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_mode("security")
    before = json.dumps(authority.policy(), sort_keys=True)
    attempts = {"n": 0}
    real = asyncio.open_connection

    async def refuse(*args, **kwargs):
        attempts["n"] += 1
        raise ConnectionRefusedError("down")

    monkeypatch.setattr(asyncio, "open_connection", refuse)

    async def fail_closed():
        with pytest.raises(StreamError):
            await async_stream_complete("http://127.0.0.1:9/v1", "", "fixture", [], timeout_s=1)

    asyncio.run(fail_closed())
    monkeypatch.setattr(asyncio, "open_connection", real)
    assert attempts["n"] == 3
    assert json.dumps(authority.policy(), sort_keys=True) == before
    assert authority.policy().get("mode") == "security"
