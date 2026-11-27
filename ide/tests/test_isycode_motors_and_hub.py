"""Tests for LinuxCommandRuntime upgrades, ISyCode guided motors, and ISyMCP Hub integration."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from core.isycode_motors import build_tool_guide, error_recovery_hint, run_isycode_motor
from core.isymcp_hub_client import ISyMCPHubClient
from core.policy import PolicyEngine
from core.runtime import RuntimeRegistry, ToolCall
from core.runtime.linux import LinuxCommandRuntime, installation_status
from core.tool_execution import ToolExecutionService


def test_linux_runtime_clamps_timeout_above_120(tmp_path):
    if not installation_status()["installed"]:
        pytest.skip("Linux bwrap runtime not available")
    rt = LinuxCommandRuntime(tmp_path)
    req = rt.prepare({"argv": ["python3", "-c", "print(1)"], "timeout": 180})
    assert req.timeout == 120


def test_linux_runtime_allows_user_local_zig(tmp_path):
    if not installation_status()["installed"]:
        pytest.skip("Linux bwrap runtime not available")
    zig = shutil.which("zig", path="/home/danny/.local/bin:/usr/local/bin:/usr/bin:/bin")
    if not zig:
        pytest.skip("zig not installed in ~/.local/bin")
    rt = LinuxCommandRuntime(tmp_path)
    req = rt.prepare({"argv": ["zig", "version"], "timeout": 30})
    report = asyncio.run(rt.run_request(req, authorize=lambda: True))
    assert report["returncode"] == 0
    assert report["stdout"].strip() != ""


def test_isycode_motor_planner_historian_inspector(tmp_path):
    (tmp_path / "README.md").write_text("# Demo Repo\nRun pytest.", encoding="utf-8")
    (tmp_path / "sample.py").write_text(
        "class ClassicDebugger:\n"
        "    def __init__(self, program: str, max_steps: int = 100):\n"
        "        self.program = program\n\n"
        "def helper(x, y):\n"
        "    return x + y\n",
        encoding="utf-8",
    )

    async def _run():
        plan_res = await run_isycode_motor(tmp_path, {"motor": "planner", "query": "test repo"})
        assert plan_res.success
        plan_data = json.loads(plan_res.stdout)
        assert "README.md" in plan_data["entrypoints_found"]
        assert "python3" in plan_data["sandbox_toolchains"]

        insp_res = await run_isycode_motor(tmp_path, {"motor": "inspector", "target": "sample.py"})
        assert insp_res.success
        insp_data = json.loads(insp_res.stdout)
        assert insp_data["kind"] == "python_ast"
        assert any(
            c["name"] == "ClassicDebugger" and "__init__(self, program, max_steps)" in c["methods"]
            for c in insp_data["classes"]
        )

        sym_res = await run_isycode_motor(tmp_path, {"motor": "inspector", "target": "ClassicDebugger"})
        assert sym_res.success
        sym_data = json.loads(sym_res.stdout)
        assert any(m["file"] == "sample.py" for m in sym_data["matches"])

        hist_res = await run_isycode_motor(tmp_path, {"motor": "historian", "query": "isycode"})
        assert hist_res.success
        hist_data = json.loads(hist_res.stdout)
        assert hist_data["motor"] == "historian"

    asyncio.run(_run())


def test_error_recovery_hints_and_tool_guide():
    assert "isycode_motor" in error_recovery_hint("run_command", "EXECUTABLE_MISSING", "")
    assert "inspector" in error_recovery_hint("run_command", "", "TypeError: missing 1 required positional argument")
    assert "120s" in error_recovery_hint("run_command", "TIMEOUT_LIMIT", "")
    assert "PLAN" in error_recovery_hint("write", "PLAN_MODE_WRITE_DENIED", "")
    guide = build_tool_guide({"available": True, "servers": [{"name": "isymcp", "tools": 45}]})
    assert guide["run_command_timeout_max_s"] == 120
    assert guide["isymcp_hub"]["available"] is True


def test_isycode_mcp_execute_requires_coder_and_approval(tmp_path):
    async def _run():
        svc = ToolExecutionService(tmp_path, PolicyEngine(), RuntimeRegistry(tmp_path))
        res_plan = await svc.execute(
            ToolCall("isycode_mcp_execute", {"server": "isymcp", "tool": "ping", "arguments": {}}, "c1"),
            mode="plan",
            actor="AGENT",
        )
        assert not res_plan.success
        assert res_plan.error_code == "PLAN_MODE_WRITE_DENIED"

        res_no_appr = await svc.execute(
            ToolCall("isycode_mcp_execute", {"server": "isymcp", "tool": "ping", "arguments": {}}, "c2"),
            mode="coder",
            actor="AGENT",
            approve=None,
        )
        assert not res_no_appr.success
        assert res_no_appr.error_code == "APPROVAL_REQUIRED"

    asyncio.run(_run())


def test_isymcp_hub_live_discover_and_route(tmp_path):
    client = ISyMCPHubClient()
    if not client.available:
        pytest.skip("isymcp-hub binary not available on this host")

    async def _run():
        disc = await client.discover(limit=10)
        assert disc["ok"], disc.get("error")
        data = json.loads(disc["text"])
        assert isinstance(data.get("servers"), list) and len(data["servers"]) > 0

        route = await run_isycode_motor(tmp_path, {"motor": "hub_route", "query": "github"})
        assert route.success
        route_data = json.loads(route.stdout)
        assert route_data["motor"] == "hub_route"

    asyncio.run(_run())
