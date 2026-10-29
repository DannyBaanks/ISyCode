"""Pyright diagnostics after edits: protocol exchange and owner authorization."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import isycode.lsp as lsp
from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import LPSSymbolOwner
from isycode.approvals import ActionApprovalStore
from isycode.lsp import _diagnostics_session
from isycode.workspace_authority import WorkspaceAuthority

FAKE_LSP = r'''
import json, sys
def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            length = int(value)
    return json.loads(sys.stdin.buffer.read(length))
def send(message):
    data = json.dumps(message).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
    sys.stdout.buffer.flush()
while True:
    message = read()
    method = message.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
    elif method == "textDocument/didOpen":
        uri = message["params"]["textDocument"]["uri"]
        send({"jsonrpc": "2.0", "id": 77, "method": "workspace/configuration",
              "params": {"items": [{"section": "python"}]}})
        read()  # the client's answer
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": "file:///workspace/other.py", "diagnostics": []}})
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {
            "uri": uri, "diagnostics": [
                {"range": {"start": {"line": 1, "character": 4}}, "severity": 1,
                 "message": '"undefined_name" is not defined', "code": "reportUndefinedVariable"},
                {"range": {"start": {"line": 0, "character": 0}}, "severity": 3,
                 "message": "info"}]}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": message["id"], "result": None})
    elif method == "exit":
        break
'''


def test_diagnostics_exchange_answers_server_requests_and_filters_by_file(tmp_path):
    script = tmp_path / "fake_lsp.py"
    script.write_text(FAKE_LSP)

    async def scenario():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        result = await _diagnostics_session(proc.stdout, proc.stdin, "project", "pkg/app.py",
                                            "x = 1\nprint(undefined_name)\n", 10)
        await asyncio.wait_for(proc.wait(), 5)
        return result

    diagnostics = asyncio.run(scenario())
    assert diagnostics[0] == {"line": 2, "column": 5, "severity": "error",
                              "message": '"undefined_name" is not defined',
                              "rule": "reportUndefinedVariable"}
    assert diagnostics[1]["severity"] == "information"


@pytest.fixture
def owner(tmp_path: Path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX sandbox only")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "bwrap"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    server = {"id": "pyright", "state": "sandbox_ready", "sandbox_executable": str(fake.resolve()),
              "server_executable": "/opt/pyright/langserver.index.js",
              "node_executable": "/usr/bin/node"}
    monkeypatch.setattr(lsp, "discover_servers", lambda: [dict(server)])
    calls = []

    async def fake_diagnostics(root, path, text, srv, timeout_s=25.0):
        calls.append(path)
        return {"server": "pyright", "path": path,
                "diagnostics": [{"line": 1, "column": 1, "severity": "error",
                                 "message": "boom", "rule": ""}]}

    monkeypatch.setattr(lsp, "pyright_diagnostics", fake_diagnostics)
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("x = \n")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    return (LPSSymbolOwner(root, authority, ActionApprovalStore()), authority, [server], calls,
            server["sandbox_executable"])


def _run(owner, path, catalog):
    return asyncio.run(owner.diagnostics("pyright", path, "x = \n", catalog))


def test_diagnostics_need_their_own_grant_and_the_read_grant(owner):
    lsp_owner, authority, catalog, calls, sandbox = owner
    assert _run(lsp_owner, "app.py", catalog).decision == "DENY"
    authority.set_grant("lsp.diagnostics", enabled=True, executables=[sandbox])
    denied = _run(lsp_owner, "app.py", catalog)
    assert denied.decision == "DENY" and "workspace.files.read" in denied.reason
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[lsp_owner.root])
    outcome = _run(lsp_owner, "app.py", catalog)
    assert outcome.decision == "ALLOW" and json.loads(outcome.text)["diagnostics"][0]["message"] == "boom"
    assert calls == ["app.py"]
    assert ActionAuditJournal(lsp_owner.root).verify().receipts == 1


@pytest.mark.parametrize("path", ["notes.txt", ".env.py", "../x.py", "/etc/x.py"])
def test_only_non_sensitive_python_files_in_the_workspace(owner, path):
    lsp_owner, authority, catalog, calls, sandbox = owner
    authority.set_grant("lsp.diagnostics", enabled=True, executables=[sandbox])
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[lsp_owner.root])
    assert _run(lsp_owner, path, catalog).decision == "DENY"
    assert calls == []


def test_a_changed_adapter_catalog_is_refused(owner):
    lsp_owner, authority, catalog, calls, sandbox = owner
    stale = [{**catalog[0], "server_executable": "/tmp/evil.js"}]
    assert _run(lsp_owner, "app.py", stale).decision == "DENY"


def test_classic_does_not_imply_diagnostics(owner):
    lsp_owner, authority, catalog, calls, _ = owner
    authority.set_mode("classic")
    assert _run(lsp_owner, "app.py", catalog).decision == "DENY"
