"""AppController tests: headless host wiring, no Qt, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ui.app import AppController


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    # Keep provider config (~/.isyvm/config.yaml) and secret fallback out
    # of the tests: Point Path.home at the temporary workspace.
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


def test_controller_builds_all_components(tmp_path):
    controller = AppController(tmp_path)
    assert controller.working_dir == tmp_path.resolve()
    assert {"openai", "openai-compatible", "anthropic", "google", "ollama", "codex-subscription", "claude-subscription", "grok-subscription"} <= set(controller.provider_types())
    assert controller.providers() == {}
    assert controller.runtime_status()["layer_a"] is True
    assert controller.runtime_status()["layer_b"] is False
    assert "linux_isolated" in controller.runtime_status()
    rules = controller.policy_rules()
    assert len(rules) == 7
    assert any(r["action"] == "network" and not r["allowed"] for r in rules)
    assert controller.mode() == "plan"  # no .isyvm/mode.json yet
    status = controller.resident_status()
    assert "components" in status and "state_root" in status
    assert controller.plans() == []
    assert controller.sessions() == []


def test_execute_tool_respects_workspace_boundary(tmp_path):
    controller = AppController(tmp_path)
    (tmp_path / "hello.txt").write_text("hola\n", encoding="utf-8")

    result = controller.execute_tool("read", {"path": "hello.txt"})
    assert result.success and result.stdout == "hola\n"

    result = controller.execute_tool("write",
                                     {"path": "sub/new.txt", "content": "x"})
    assert result.success
    assert (tmp_path / "sub" / "new.txt").read_text(encoding="utf-8") == "x"

    result = controller.execute_tool("read", {"path": "../escape.txt"})
    assert not result.success
    assert result.error_code == "PATH_OUTSIDE_WORKSPACE"

    result = controller.execute_tool("bash", {"command": "dir"})
    assert not result.success
    assert result.error_code == "UNAVAILABLE_TOOL"


def test_mode_toggle_persists(tmp_path):
    controller = AppController(tmp_path)
    assert controller.set_mode("coder") == "coder"
    assert controller.mode() == "coder"
    assert json.loads((tmp_path / ".isycode-ide" / "mode.json").read_text()) == {
        "mode": "coder"}
    assert controller.toggle_mode() == "plan"


def test_verify_contracts_delegates_to_real_verifier(tmp_path, monkeypatch):
    controller = AppController(tmp_path)
    monkeypatch.setattr(
        "verifier.contract_verifier.write_report", lambda results: None)
    summary = controller.verify_contracts()
    assert summary
    for target, data in summary.items():
        assert data["total"] > 0
        assert 0 <= data["passed"] <= data["total"]


def test_import_opencode_keys(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"nvidia": "nvapi-abc", "openai": "sk-xyz"}),
                    encoding="utf-8")
    controller = AppController(tmp_path)
    imported = controller.import_opencode_keys(auth)
    assert imported.get("nvidia") == "keyring"
    assert controller.has_key("nvidia")
    assert controller.secret_broker.get("nvidia") == "nvapi-abc"


def test_resident_scan_uses_real_scanner(tmp_path):
    controller = AppController(tmp_path)
    (tmp_path / "demo.py").write_text("print('x')\n", encoding="utf-8")
    result = controller.resident_scan()
    assert result["status"] == "ok"
    assert result["components"] >= 1


def test_bridge_contracts_read_only(tmp_path):
    controller = AppController(tmp_path)
    contracts = controller.bridge_contracts()
    assert isinstance(contracts, list)
    assert contracts and all(name.endswith(".iesy") for name in contracts)
    # GOLDEN 1 documented call: read_contract resolves flat under the root.
    text = controller.bridge_read_contract("bootstrap/bootstrap.iesy")
    assert "Identity:" in text