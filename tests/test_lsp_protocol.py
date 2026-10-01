import asyncio
import subprocess

import pytest

from isycode.lsp import (
    _SECCOMP_BOOTSTRAP, _sandbox_command, _server_request_response,
    discover_servers, pyright_workspace_symbols,
)


def test_workspace_configuration_is_answered_with_bounded_empty_config():
    request = {
        "jsonrpc": "2.0", "id": 41, "method": "workspace/configuration",
        "params": {"items": [{"section": "python"}, {"section": "pyright"}]},
    }

    assert _server_request_response(request) == {
        "jsonrpc": "2.0", "id": 41, "result": [None, None],
    }


def test_unknown_server_request_is_rejected_instead_of_deadlocking():
    response = _server_request_response({
        "jsonrpc": "2.0", "id": 9, "method": "workspace/executeCommand",
    })

    assert response == {
        "jsonrpc": "2.0", "id": 9,
        "error": {"code": -32601, "message": "Client request is not supported"},
    }


def test_server_notification_needs_no_client_response():
    assert _server_request_response({
        "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {},
    }) is None


def test_pyright_initialize_and_workspace_symbol_handshake(tmp_path):
    server = next((item for item in discover_servers() if item["id"] == "pyright"), None)
    if not server or server["state"] != "sandbox_ready":
        pytest.skip("sandboxed Pyright runtime is not installed")
    (tmp_path / "sample.py").write_text(
        "class HandshakeWitness:\n    pass\n", encoding="utf-8")

    result = asyncio.run(pyright_workspace_symbols(
        tmp_path, "HandshakeWitness", server, timeout_s=10))

    assert result["protocol"] == "LSP"
    assert any(item.get("name") == "HandshakeWitness" for item in result["symbols"])
    assert result["sandbox"]["read_only_workspace"] is True


def test_lsp_sandbox_denies_sockets_and_workspace_writes(tmp_path):
    server = next((item for item in discover_servers() if item["id"] == "pyright"), None)
    if not server or server["state"] != "sandbox_ready":
        pytest.skip("sandboxed Pyright runtime is not installed")
    base = _sandbox_command(tmp_path, server)
    separator = base.index("--")
    command_prefix = base[:separator + 1]
    probes = (
        ("import socket\ntry:\n socket.socket()\nexcept PermissionError:\n print('network-denied')\nelse:\n raise SystemExit(1)",
         "network-denied"),
        ("from pathlib import Path\ntry:\n Path('/workspace/forbidden').write_text('x')\nexcept OSError:\n print('workspace-read-only')\nelse:\n raise SystemExit(1)",
         "workspace-read-only"),
    )
    for script, expected in probes:
        result = subprocess.run(
            command_prefix + ["/usr/bin/python3", "-c", _SECCOMP_BOOTSTRAP,
                              "/usr/bin/python3", "-c", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=10, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
