"""Receipt witnesses for connected owners with all remote/process effects stubbed."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import (
    GatewayMCPInvocationOwner,
    GatewaySemanticOwner,
    LPSSymbolOwner,
    ProviderNetworkOwner,
)
from isycode.approvals import ActionApprovalStore
from isycode.gateway_mcp import tool_schema_digest
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def _assert_durable_receipt(root: Path, result: Any, expected_action: str,
                            expected_decisions: int, state: Path) -> None:
    assert result.decision == "ALLOW"
    assert result.receipt is not None
    assert result.receipt.action_id == expected_action
    report = ActionAuditJournal.for_read_only_inspection(
        root, state_directory=state / "action-audit").verify()
    assert report.status == "PASS"
    assert report.decisions == expected_decisions
    assert report.receipts == 1
    assert report.unverifiable == 0
    assert all(item.get("receipt_id") for item in report.recent if item.get("kind") == "receipt")


def test_gateway_mcp_owner_persists_approved_result_receipt(tmp_path, monkeypatch):
    import isycode.gateway_mcp as gateway_mcp

    root = tmp_path / "workspace"
    root.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    url = "http://127.0.0.1:8787"
    target = GatewayMCPInvocationOwner.target_for(url)
    schema = {"name": "fixture.read", "inputSchema": {"type": "object", "properties": {}}}
    digest = tool_schema_digest(schema)
    request = ActionRequest(
        "mcp.invoke", root, target,
        {"server": "isyco-gateway", "tool": "fixture.read", "arguments": {},
         "url": url, "schema_digest": digest},
        execution_owner="gateway_mcp")
    authority.set_grant("mcp.invoke", enabled=True, targets=[target])
    approval = approvals.issue(request)
    calls: list[tuple[str, dict[str, Any], str | None]] = []

    async def fake_invoke(name: str, arguments: dict[str, Any], *, base_url: str | None = None):
        calls.append((name, arguments, base_url))
        return {"content": [{"type": "text", "text": "fixture result"}]}

    monkeypatch.setattr(gateway_mcp, "invoke_gateway_tool", fake_invoke)
    owner = GatewayMCPInvocationOwner(root, authority, approvals)
    result = asyncio.run(owner.invoke(
        "fixture.read", {}, url, digest, [schema], approval))

    assert calls == [("fixture.read", {}, url)]
    assert result.receipt is not None and result.receipt.verify(
        request, '{"content": [{"text": "fixture result", "type": "text"}]}')
    _assert_durable_receipt(root, result, "mcp.invoke", 1, state)


def test_semantic_gateway_owner_persists_identity_bound_receipt(tmp_path, monkeypatch):
    import isycode.semantic_gateway as semantic_gateway

    root = tmp_path / "workspace"
    root.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    monkeypatch.setenv("ISYCODE_GATEWAY_WORKSPACE_ID", "workspace-fixture")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    url = "http://127.0.0.1:8787"
    workspace_id = "workspace-fixture"
    host = "127.0.0.1:8787"
    payload = {"query": "needle"}
    request = ActionRequest(
        "gateway.semantic.read", root, host,
        {"url": url, "operation": "symbols/search", "payload": payload,
         "workspace_id": workspace_id},
        execution_owner="gateway_semantic")
    authority.set_grant("gateway.semantic.read", enabled=True, network_hosts=[host])
    approval = approvals.issue(request)
    calls: list[tuple[str, dict[str, Any], str]] = []

    class FakeClient:
        def __init__(self, *, base_url: str | None = None):
            assert base_url == url

        def workspace_identity(self) -> str:
            return workspace_id

        def call(self, operation: str, args: dict[str, Any], *, workspace_id: str | None = None):
            assert workspace_id is not None
            calls.append((operation, args, workspace_id))
            return {"results": [{"name": "FixtureSymbol"}]}

    monkeypatch.setattr(semantic_gateway, "SemanticGatewayClient", FakeClient)
    owner = GatewaySemanticOwner(root, authority, approvals)
    result = owner.invoke("symbols/search", payload, url, workspace_id, approval)

    assert calls == [("symbols/search", payload, workspace_id)]
    assert result.receipt is not None
    assert result.receipt.verify(request, '{"results": [{"name": "FixtureSymbol"}]}')
    _assert_durable_receipt(root, result, "gateway.semantic.read", 1, state)


def test_lsp_owner_persists_receipt_after_read_grant_and_start_approval(tmp_path, monkeypatch):
    import isycode.lsp as lsp

    root = tmp_path / "workspace"
    root.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    paths = {}
    for name in ("bwrap", "node", "pyright-langserver"):
        path = binaries / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o700)
        paths[name] = str(path.resolve())
    server = {
        "id": "pyright", "state": "sandbox_ready",
        "sandbox_executable": paths["bwrap"],
        "node_executable": paths["node"],
        "server_executable": paths["pyright-langserver"],
    }
    monkeypatch.setattr(lsp, "discover_servers", lambda: [server])
    monkeypatch.setattr("isycode.action_runtime.shutil.which", lambda name: paths.get(name))
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("lsp.start", enabled=True, executables=[paths["bwrap"]])
    request = ActionRequest(
        "lsp.start", root, "pyright",
        {"operation": "workspace/symbol", "server_id": "pyright", "query": "Fixture",
         "workspace_root": str(root), "executable": paths["bwrap"],
         "server_executable": paths["pyright-langserver"],
         "node_executable": paths["node"]},
        execution_owner="lsp_symbols")
    approval = approvals.issue(request)
    calls: list[tuple[Path, str, dict[str, Any]]] = []

    async def fake_symbols(workspace: Path, query: str, selected: dict[str, Any]):
        calls.append((workspace, query, selected))
        return {"symbols": [{"name": "FixtureSymbol"}]}

    monkeypatch.setattr(lsp, "pyright_workspace_symbols", fake_symbols)
    owner = LPSSymbolOwner(root, authority, approvals)
    result = asyncio.run(owner.search("pyright", "Fixture", approval, [server]))

    assert calls == [(root.resolve(), "Fixture", server)]
    expected = '{"symbols": [{"name": "FixtureSymbol"}]}'
    assert result.receipt is not None and result.receipt.verify(request, expected)
    _assert_durable_receipt(root, result, "lsp.start", 2, state)


def test_provider_owner_binds_prompt_digest_and_persists_result_receipt(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("provider.request", enabled=True,
                        network_hosts=["127.0.0.1:9911"])
    approvals = ActionApprovalStore()
    owner = ProviderNetworkOwner(root, authority)

    class FixtureProvider:
        name = "fixture"
        model = "fixture-model"
        base_url = "http://127.0.0.1:9911/v1"

    sent: list[str] = []

    async def send():
        sent.append("called")
        return {"text": "fixture answer", "usage": {"completion_tokens": 2}}

    response, outcome = asyncio.run(owner.execute(
        FixtureProvider(), {"messages": [{"role": "user", "content": "hello"}]}, send))

    assert sent == ["called"]
    assert response == {"text": "fixture answer", "usage": {"completion_tokens": 2}}
    assert outcome.receipt is not None
    _assert_durable_receipt(root, outcome, "provider.request", 1, state)


def test_provider_owner_deny_never_calls_transport(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    owner = ProviderNetworkOwner(root, authority)

    class FixtureProvider:
        name = "fixture"
        model = "fixture-model"
        base_url = "https://provider.example.test/v1"

    sent = False

    async def send():
        nonlocal sent
        sent = True
        return {"text": "must not be sent"}

    response, outcome = asyncio.run(owner.execute(FixtureProvider(), {"prompt": "hi"}, send))

    assert outcome.decision == "DENY"
    assert response is None
    assert not sent
