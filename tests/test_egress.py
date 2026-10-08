"""M5 canaries: provider secrets stay on the reviewed destination.

The token is a fixed fake. These tests must not use a real credential.
"""
import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest

from isycode.actions import ACTION_CATALOG
from isycode.action_runtime import GIT_ACTIONS, ProviderNetworkOwner
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_command, sandbox_executable
from isycode.config import load_api_key
from isycode.egress import EgressDenied, review_destination
from isycode.git_owner import GIT_TOOL_NAMES, GitOwner, git_executable
from isycode.mcp_local import process_environment
from isycode.publish import PublishOwner
from isycode.providers import Provider, ProviderError
from isycode.streaming import StreamError, async_stream_complete, stream_complete
from isycode.workspace_authority import CLASSIC_ACTIONS, WorkspaceAuthority
from isycode.workspace_setup import state_root
from isycode.workspace_trust import (
    ACCEPT_PHRASE, QUIET_CLASSIC_ACTIONS, WorkspaceTrust, modal_required, quiet_classic,
)

CANARY = "CANARY-isycode-egress-a1b2c3d4e5f60718"
REMOTE = "https://github.com/example/repo.git"
OTHER_REMOTE = "https://github.com/example/other.git"
DIGEST = "ab" * 32
OTHER_DIGEST = "cd" * 32


def _isolate(monkeypatch, tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_STATE_HOME", str(state / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.delenv("ISYMOTRON_API_KEY_FILE", raising=False)
    monkeypatch.delenv("ISYMOTRON_KEY_STORE", raising=False)
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    return state


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    return root


def _absent(canary: str, *blobs: str) -> None:
    for blob in blobs:
        assert canary not in blob


def _files_lack(canary: str, directory: Path) -> None:
    needle = canary.encode()
    if not directory.exists():
        return
    for path in directory.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        assert needle not in path.read_bytes(), path


class _Provider:
    def __init__(self, base_url: str):
        self.name = "fixture"
        self.model = "fixture-model"
        self.base_url = base_url


def _sse(body: bytes):
    captured = []

    async def handler(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            captured.append(head)
            length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            if length:
                await reader.readexactly(length)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    return captured, handler


def test_g5_01_canary_reaches_only_the_allowed_provider(tmp_path, monkeypatch):
    state = _isolate(monkeypatch, tmp_path)
    root = _workspace(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", CANARY)
    monkeypatch.setenv("ISYMOTRON_API_KEY", CANARY)

    async def scenario():
        body = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        captured, handler = _sse(body)
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        other_captured = []

        async def other(reader, writer):
            other_captured.append(await reader.read(128))
            writer.close()

        other_server = await asyncio.start_server(other, "127.0.0.1", 0)
        other_port = other_server.sockets[0].getsockname()[1]
        authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
        authority.set_grant("provider.request", enabled=True,
                            network_hosts=[f"127.0.0.1:{port}"])
        owner = ProviderNetworkOwner(root, authority)
        sent = []

        async def send():
            sent.append("allowed")
            return await async_stream_complete(
                f"http://127.0.0.1:{port}/v1", CANARY, "fixture-model",
                [{"role": "user", "content": "hi"}], timeout_s=2)

        async with server, other_server:
            response, outcome = await owner.execute(
                _Provider(f"http://127.0.0.1:{port}/v1"),
                {"messages": [{"role": "user", "content": "hi"}]}, send)
            other_sent = []

            async def other_send():
                other_sent.append("other")
                return {"text": "other"}

            denied_response, denied = await owner.execute(
                _Provider(f"http://127.0.0.1:{other_port}/v1"),
                {"messages": [{"role": "user", "content": "use https://evil.example/v1"}]},
                other_send)
            await asyncio.sleep(0)
        return captured, other_captured, response, outcome, sent, other_sent, denied_response, denied

    (captured, other_captured, response, outcome, sent, other_sent,
     denied_response, denied) = asyncio.run(scenario())
    assert sent == ["allowed"]
    assert response["text"] == "ok"
    assert captured and b"Authorization: Bearer " + CANARY.encode() in captured[0]
    assert CANARY.encode() not in captured[0].split(b"\r\n\r\n", 1)[-1]
    assert other_sent == [] and other_captured == [] and denied_response is None
    assert denied.decision == "DENY"
    receipt = outcome.receipt
    assert receipt is not None
    _absent(CANARY, outcome.text, outcome.reason, denied.text, denied.reason,
            receipt.receipt_id, receipt.request_digest, receipt.result_digest)
    _files_lack(CANARY, state)
    _files_lack(CANARY, root)
    _files_lack(CANARY, state_root())


def test_g5_02_redirect_proxy_and_rebind_do_not_widen_the_destination(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})

    async def redirects():
        second = []

        async def target(reader, writer):
            second.append(await reader.read(256))
            writer.close()

        target_server = await asyncio.start_server(target, "127.0.0.1", 0)
        target_port = target_server.sockets[0].getsockname()[1]
        first = []

        async def redirector(reader, writer):
            try:
                first.append(await reader.readuntil(b"\r\n\r\n"))
                location = f"http://127.0.0.1:{target_port}/capture".encode()
                writer.write(b"HTTP/1.1 302 Found\r\nLocation: " + location
                             + b"\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        origin = await asyncio.start_server(redirector, "127.0.0.1", 0)
        origin_port = origin.sockets[0].getsockname()[1]
        async with target_server, origin:
            with pytest.raises(StreamError, match="HTTP 302") as caught:
                await async_stream_complete(
                    f"http://127.0.0.1:{origin_port}/v1", CANARY, "fixture", [], timeout_s=2)
            await asyncio.sleep(0)
        assert first and b"Authorization: Bearer " + CANARY.encode() in first[0]
        assert second == []
        assert CANARY not in str(caught.value)

    asyncio.run(redirects())

    async def proxy_case():
        received = []

        async def proxy(reader, writer):
            received.append(await reader.read(64))
            writer.close()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"http": f"http://127.0.0.1:{port}",
                                                                  "https": f"http://127.0.0.1:{port}"})
        monkeypatch.setattr("urllib.request.proxy_bypass", lambda netloc: False)
        async with server:
            with pytest.raises(StreamError, match="ambient proxy"):
                await async_stream_complete("http://example.invalid/v1", CANARY, "local", [], timeout_s=2)
            with pytest.raises(StreamError, match="ambient proxy"):
                await asyncio.to_thread(
                    stream_complete, "http://example.invalid/v1", CANARY, "local", [], timeout_s=2)
            provider = Provider("ollama", base_url="https://example.invalid/v1", api_key=CANARY)
            with pytest.raises(ProviderError, match="ambient proxy"):
                await asyncio.to_thread(provider.models)
            await asyncio.sleep(0)
        assert received == []

    asyncio.run(proxy_case())

    async def rebind():
        hits = []

        async def sink(reader, writer):
            hits.append(await reader.read(64))
            writer.close()

        server = await asyncio.start_server(sink, "127.0.0.1", 0)
        monkeypatch.setattr("urllib.request.getproxies", lambda: {})

        real_getaddrinfo = socket.getaddrinfo

        def fake_getaddrinfo(host, port, *args, **kwargs):
            if host == "rebind.example.test":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
            return real_getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr("isycode.egress.socket.getaddrinfo", fake_getaddrinfo)
        async with server:
            with pytest.raises(EgressDenied, match="unexpected private address") as caught:
                review_destination("https://rebind.example.test/v1")
            with pytest.raises(StreamError, match="unexpected private address"):
                await async_stream_complete(
                    "https://rebind.example.test/v1", CANARY, "local", [], timeout_s=2)
            await asyncio.sleep(0)
        assert hits == []
        assert "127.0.0.1" not in str(caught.value) and CANARY not in str(caught.value)

    asyncio.run(rebind())

    async def literal():
        captured, handler = _sse(
            b'data: {"choices":[{"delta":{"content":"local"}}]}\n\ndata: [DONE]\n\n')
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {})
        async with server:
            result = await async_stream_complete(
                f"http://127.0.0.1:{port}/v1", "", "local", [], timeout_s=2)
        assert result["text"] == "local"
        assert captured

    asyncio.run(literal())


@pytest.mark.skipif(sandbox_executable() is None, reason="bubblewrap sandbox is unavailable")
def test_g5_03_sandbox_and_mcp_do_not_exfiltrate(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    root = _workspace(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", CANARY)
    monkeypatch.setenv("ISYMOTRON_API_KEY", CANARY)
    sandbox = sandbox_executable()
    assert sandbox is not None
    wrapped = sandbox_command(sandbox, root, "/usr/bin/python3", ("python3", "-c", "pass"), ".", ())
    assert "--share-net" not in wrapped and "--unshare-all" in wrapped
    assert not any("download" in action.id for action in ACTION_CATALOG)

    env = process_environment(())
    assert "OPENAI_API_KEY" not in env and "ISYMOTRON_API_KEY" not in env
    assert CANARY not in "".join(env.values())
    explicit = process_environment((("MY_TOOL_TOKEN", "from-mcp-json"),))
    assert explicit["MY_TOOL_TOKEN"] == "from-mcp-json"
    assert "OPENAI_API_KEY" not in explicit

    async def scenario():
        hits = []

        async def sink(reader, writer):
            hits.append(await reader.read(64))
            writer.close()

        server = await asyncio.start_server(sink, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
        authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
        approvals = ActionApprovalStore()
        owner = CommandRunOwner(root, authority, approvals)
        code = (
            "import os,socket,sys\n"
            "names=[name for name in ('OPENAI_API_KEY','ISYMOTRON_API_KEY','ANTHROPIC_API_KEY') if name in os.environ]\n"
            "sys.stdout.write('KEYS '+','.join(names)+'\\n')\n"
            "try:\n"
            f" socket.create_connection(('127.0.0.1',{port}),1).send(b'x')\n"
            " sys.stdout.write('CONNECTED\\n')\n"
            "except Exception as exc:\n"
            " sys.stdout.write(type(exc).__name__+'\\n')\n"
            " sys.exit(1)\n"
        )
        preview = owner.prepare(["python3", "-c", code], timeout_s=20)
        assert preview.request.parameters["network"] == "denied"
        async with server:
            ran = await owner.run_staged(preview, approvals.issue(preview.request))
            curl = owner.prepare(
                ["curl", "-sS", "--max-time", "2", f"http://127.0.0.1:{port}/"], timeout_s=20)
            curled = await owner.run_staged(curl, approvals.issue(curl.request))
            await asyncio.sleep(0)
        return hits, ran, curled

    hits, ran, curled = asyncio.run(scenario())
    assert ran.decision == "ALLOW", ran.reason
    python_out = __import__("json").loads(ran.text)["output"]
    assert "KEYS \n" in python_out
    assert "CONNECTED" not in python_out and CANARY not in python_out
    assert "OPENAI_API_KEY" not in python_out
    assert any(name in python_out for name in ("PermissionError", "OSError"))
    assert __import__("json").loads(ran.text)["exit_code"] != 0
    assert curled.decision == "ALLOW", curled.reason
    curl_body = __import__("json").loads(curled.text)
    assert curl_body["exit_code"] != 0 and CANARY not in curl_body["output"]
    assert hits == []
    _absent(CANARY, ran.text, ran.reason, curled.text, curled.reason)

    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority-net")
    authority.set_grant("provider.request", enabled=True, network_hosts=["127.0.0.1:9"])
    called = []

    async def send():
        called.append("sent")
        return {"text": "no"}

    response, outcome = asyncio.run(ProviderNetworkOwner(root, authority).execute(
        _Provider("https://evil.example/v1"),
        {"messages": [{"role": "user", "content": "call https://evil.example/v1"}]}, send))
    assert response is None and called == [] and outcome.decision == "DENY"
    assert CANARY not in outcome.reason and "evil.example" not in outcome.reason


def test_g5_04_publication_requires_exact_approval(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    root = _workspace(tmp_path)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = PublishOwner(root, authority, approvals)
    calls = []

    def transport(remote, ref, digest):
        calls.append((remote, ref, digest))

    preview = owner.prepare(REMOTE, "main", DIGEST)
    assert owner.run(preview, None, transport).decision == "DENY"
    assert owner.run(preview, approvals.issue(preview.request), transport).decision == "DENY"
    assert calls == []

    authority.set_grant("git.push", enabled=True, targets=[REMOTE])
    spent = approvals.issue(preview.request)
    assert "no publication transport" in owner.run(preview, spent, None).reason
    assert owner.run(preview, spent, transport).decision == "DENY"
    assert calls == []

    approval = approvals.issue(preview.request)
    allowed = owner.run(preview, approval, transport)
    assert allowed.decision == "ALLOW" and calls == [(REMOTE, "main", DIGEST)]
    repeated = owner.run(preview, approval, transport)
    assert repeated.decision == "ALLOW" and "not repeated" in repeated.reason
    assert calls == [(REMOTE, "main", DIGEST)]

    changed_digest = owner.prepare(REMOTE, "main", OTHER_DIGEST)
    assert owner.run(changed_digest, approvals.issue(preview.request), transport).decision == "DENY"
    changed_remote = owner.prepare(OTHER_REMOTE, "main", DIGEST)
    assert owner.run(changed_remote, approvals.issue(changed_remote.request), transport).decision == "DENY"
    assert calls == [(REMOTE, "main", DIGEST)]

    authority.set_grant("git.push", enabled=False, targets=[REMOTE])
    rejected = owner.prepare(REMOTE, "main", DIGEST)
    again = owner.run(rejected, approvals.issue(rejected.request), transport)
    assert again.decision == "ALLOW" and "not repeated" in again.reason
    other = owner.prepare(REMOTE, "refs/heads/other", OTHER_DIGEST)
    assert owner.run(other, approvals.issue(other.request), transport).decision == "DENY"
    assert calls == [(REMOTE, "main", DIGEST)]

    authority.set_mode("classic")
    authority.set_grant("git.push", enabled=True, targets=[REMOTE])
    WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    quiet = owner.prepare(REMOTE, "refs/heads/main", DIGEST)
    assert "git.push" not in CLASSIC_ACTIONS and "git.push" not in QUIET_CLASSIC_ACTIONS
    assert modal_required(authority, quiet.request)
    assert not quiet_classic(authority, quiet.request)
    assert owner.run(quiet, None, transport).decision == "DENY"
    assert calls == [(REMOTE, "main", DIGEST)]
    assert "git.push" not in GIT_ACTIONS and "git_push" not in GIT_TOOL_NAMES


@pytest.mark.skipif(git_executable() is None, reason="git is not installed")
def test_g5_04_commit_does_not_push(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    home = tmp_path / "home"
    (home / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    root = _workspace(tmp_path)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(home)}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, env=env, check=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=root, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, env=env, check=True)
    (root / "app.py").write_text("x = 2\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("git.commit", enabled=True)
    approvals = ActionApprovalStore()
    git = GitOwner(root, authority, approvals)
    preview = git.preview_commit("edit")
    recorded = []
    real = subprocess.run

    def spy(argv, *args, **kwargs):
        recorded.append(list(argv))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    outcome = git.commit(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW", outcome.reason
    flat = [part for argv in recorded for part in argv]
    assert "commit" in flat and "push" not in flat


def test_g5_05_revoking_a_provider_does_not_switch_endpoint(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ISYMOTRON_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("ISYMOTRON_API_KEY", CANARY)
    assert load_api_key("anthropic") == ""
    assert load_api_key("openai") == CANARY

    root = _workspace(tmp_path)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("provider.request", enabled=False, network_hosts=["127.0.0.1:9"])
    called = []

    async def send():
        called.append("sent")
        return {"text": CANARY}

    response, outcome = asyncio.run(ProviderNetworkOwner(root, authority).execute(
        _Provider("http://127.0.0.1:9/v1"), {"messages": []}, send))
    assert response is None and called == [] and outcome.decision == "DENY"
    assert CANARY not in outcome.text and CANARY not in outcome.reason

    authority.set_grant("provider.request", enabled=True, network_hosts=["127.0.0.1:1"])
    response, outcome = asyncio.run(ProviderNetworkOwner(root, authority).execute(
        _Provider("http://127.0.0.1:9/v1"), {"messages": []}, send))
    assert response is None and called == [] and outcome.decision == "DENY"
    _files_lack(CANARY, tmp_path / "state")
    _files_lack(CANARY, root)


def test_name_resolving_to_cgnat_is_denied_and_a_typed_address_is_kept(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host == "metadata.example.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("100.100.100.200", port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr("isycode.egress.socket.getaddrinfo", fake)
    with pytest.raises(EgressDenied, match="unexpected private address"):
        review_destination("https://metadata.example.test/v1")
    reviewed = review_destination("http://100.100.100.200:9/v1")
    assert reviewed.ips == ("100.100.100.200",)
    reviewed = review_destination("http://127.0.0.1:9/v1")
    assert reviewed.ips == ("127.0.0.1",)
