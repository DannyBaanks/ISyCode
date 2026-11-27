"""Tests for native ISyCode agent tools (git, worktrees, isymem, mcp, file ops) and PLAN notice."""

from __future__ import annotations

import asyncio
import json
import subprocess

from core.policy import PolicyEngine
from core.runtime import RuntimeRegistry, ToolCall
from core.tool_execution import ToolExecutionService


def _init_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@isyco.local"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "hello.txt").write_text("hola\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "hello.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)


def test_isycode_readonly_tools_work_in_plan_mode(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "hello.txt").write_text("hola mundo\n", encoding="utf-8")
    mem = tmp_path / "docs" / "agent" / "memory"
    mem.mkdir(parents=True)
    (mem / "hub-demo.md").write_text("---\nname: Demo\nproject: demo\n---\nRegla importante de prueba.\n", encoding="utf-8")

    svc = ToolExecutionService(tmp_path, PolicyEngine(), RuntimeRegistry(tmp_path))

    st = asyncio.run(svc.execute(ToolCall("isycode_git_status", {}, "t1"), mode="plan"))
    assert st.success and "hello.txt" in st.stdout

    df = asyncio.run(svc.execute(ToolCall("isycode_git_diff", {}, "t2"), mode="plan"))
    assert df.success and "+hola mundo" in df.stdout

    lg = asyncio.run(svc.execute(ToolCall("isycode_git_log", {"limit": 5}, "t3"), mode="plan"))
    assert lg.success and "init" in lg.stdout

    wt = asyncio.run(svc.execute(ToolCall("isycode_worktrees", {}, "t4"), mode="plan"))
    assert wt.success and len(json.loads(wt.stdout)["worktrees"]) >= 1

    rec = asyncio.run(svc.execute(ToolCall("isycode_isymem_recall", {"query": "importante"}, "t5"), mode="plan"))
    assert rec.success and json.loads(rec.stdout)["found"] >= 1

    mcp = asyncio.run(svc.execute(ToolCall("isycode_mcp_servers", {}, "t6"), mode="plan"))
    assert mcp.success and "hub_8798_active" in json.loads(mcp.stdout)


def test_isycode_mutating_tools_denied_in_plan_and_approved_in_coder(tmp_path):
    svc = ToolExecutionService(tmp_path, PolicyEngine(), RuntimeRegistry(tmp_path))

    # Denied in PLAN
    denied = asyncio.run(svc.execute(ToolCall("isycode_mkdir", {"path": "sub"}, "m1"), mode="plan"))
    assert not denied.success and denied.error_code == "PLAN_MODE_WRITE_DENIED"

    async def approve_yes(_preview):
        return True

    # Allowed in CODER with approval
    mk = asyncio.run(svc.execute(ToolCall("isycode_mkdir", {"path": "sub/nested"}, "m2"), mode="coder", approve=approve_yes))
    assert mk.success and (tmp_path / "sub" / "nested").is_dir()

    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    mv = asyncio.run(svc.execute(ToolCall("isycode_move_file", {"src": "a.txt", "dst": "sub/b.txt"}, "m3"), mode="coder", approve=approve_yes))
    assert mv.success and (tmp_path / "sub" / "b.txt").is_file() and not (tmp_path / "a.txt").exists()

    dl = asyncio.run(svc.execute(ToolCall("isycode_delete_file", {"path": "sub/b.txt"}, "m4"), mode="coder", approve=approve_yes))
    assert dl.success and not (tmp_path / "sub" / "b.txt").exists()

    # Outside workspace always denied
    esc = asyncio.run(svc.execute(ToolCall("isycode_delete_file", {"path": "../outside.txt"}, "m5"), mode="coder", approve=approve_yes))
    assert not esc.success and esc.error_code == "PATH_OUTSIDE_WORKSPACE"
