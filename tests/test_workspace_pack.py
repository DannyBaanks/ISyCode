from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_pack import WorkspacePackOwner


def _authority(root: Path, state: Path) -> WorkspaceAuthority:
    authority = WorkspaceAuthority(root, state_directory=state)
    authority.set_grant("workspace.files.list", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    return authority


def test_workspace_pack_reviews_exact_files_and_returns_untrusted_bounded_content(tmp_path):
    root = tmp_path / "project"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (source / "readme.md").write_text("# Project\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=never-read\n", encoding="utf-8")
    (root / ".hidden-note").write_text("hidden by broad directory selection\n",
                                       encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "vendor.js").write_text("ignored\n", encoding="utf-8")
    (root / "outside.txt").write_text("outside\n", encoding="utf-8")

    owner = WorkspacePackOwner(root, _authority(root, tmp_path / "authority"))
    preview = owner.prepare({"paths": ["src"], "token_budget": 1000})
    assert [item.path for item in preview.files] == ["src/main.py", "src/readme.md"]
    assert preview.total_bytes == len("print('hello')\n# Project\n")
    assert preview.estimated_tokens <= 1000

    result = owner.execute(preview)
    assert result["status"] == "packed"
    assert result["files"] == ["src/main.py", "src/readme.md"]
    assert result["estimated_tokens"] <= result["token_budget"]
    assert "UNTRUSTED WORKSPACE DATA" in result["content"]
    assert "print('hello')" in result["content"]
    assert "API_KEY" not in result["content"]
    assert "vendor.js" not in result["content"]

    hidden_preview = owner.prepare({"paths": [".hidden-note"], "token_budget": 1000})
    assert [item.path for item in hidden_preview.files] == [".hidden-note"]


def test_workspace_pack_can_read_a_file_larger_than_normal_tool_result_limit(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    content = "def example():\n    return '" + ("x" * 35_000) + "'\n"
    (root / "large.py").write_text(content, encoding="utf-8")
    owner = WorkspacePackOwner(root, _authority(root, tmp_path / "authority"))

    result = owner.execute(owner.prepare({
        "paths": ["large.py"], "token_budget": 100_000,
    }))

    assert len(result["content"]) > 24_000
    assert content in result["content"]


def test_workspace_pack_refuses_bad_paths_and_over_budget_before_reading(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "small.py").write_text("x\n", encoding="utf-8")
    owner = WorkspacePackOwner(root, _authority(root, tmp_path / "authority"))

    with pytest.raises(ValueError, match="within the workspace"):
        owner.prepare({"paths": ["../outside"], "token_budget": 100})
    with pytest.raises(ValueError, match="exceeds budget"):
        owner.prepare({"paths": ["small.py"], "token_budget": 1})
    with pytest.raises(ValueError, match="paths and token_budget"):
        owner.prepare({"paths": ["small.py"]})


def test_workspace_pack_requires_listing_and_read_grants(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "file.txt").write_text("private\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    owner = WorkspacePackOwner(root, authority)
    with pytest.raises(RuntimeError, match="listing denied"):
        owner.prepare({"paths": ["file.txt"], "token_budget": 100})

    authority.set_grant("workspace.files.list", enabled=True, path_prefixes=[root])
    preview = owner.prepare({"paths": ["file.txt"], "token_budget": 1000})
    with pytest.raises(RuntimeError, match="listing denied|read denied"):
        owner.execute(preview)


def test_workspace_pack_detects_file_changes_after_review(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "file.txt"
    target.write_text("before\n", encoding="utf-8")
    owner = WorkspacePackOwner(root, _authority(root, tmp_path / "authority"))
    preview = owner.prepare({"paths": ["file.txt"], "token_budget": 1000})
    target.write_text("changed after review\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="selection changed after review"):
        owner.execute(preview)


def test_workspace_pack_confirmation_cancel_reads_no_file_contents(tmp_path, monkeypatch):
    from isycode.tui_app_tools import ToolMixin
    from isycode import tui_app_tools

    root = tmp_path / "project"
    root.mkdir()
    (root / "file.txt").write_text("do not read unless approved\n", encoding="utf-8")
    authority = _authority(root, tmp_path / "authority")
    monkeypatch.setattr(tui_app_tools, "WorkspaceAuthority", lambda _: authority)
    calls: list[str] = []
    original_execute = LocalWorkspaceReadOwner.execute
    original_pack_read = LocalWorkspaceReadOwner.execute_pack_read

    def tracked_execute(self, action_id, arguments):
        calls.append(action_id)
        return original_execute(self, action_id, arguments)

    def tracked_pack_read(self, path):
        calls.append("workspace.files.read")
        return original_pack_read(self, path)

    monkeypatch.setattr(LocalWorkspaceReadOwner, "execute", tracked_execute)
    monkeypatch.setattr(LocalWorkspaceReadOwner, "execute_pack_read", tracked_pack_read)

    class Host(ToolMixin):
        _workspace_root = root
        allow = False

        async def _await_screen(self, screen):
            self.screen = screen
            return self.allow

        def _append(self, message, color=None):
            pass

    host = Host()
    response = json.loads(asyncio.run(host._call_workspace_pack(
        {"paths": ["file.txt"], "token_budget": 1000})))
    assert response == {"status": "cancelled", "files_read": 0}
    assert host.screen.details.count("file.txt") == 1
    assert calls == ["workspace.files.list"]

    approved = Host()
    approved.allow = True
    response = asyncio.run(approved._call_workspace_pack(
        {"paths": ["file.txt"], "token_budget": 1000}))
    assert "UNTRUSTED WORKSPACE DATA" in response
    assert "do not read unless approved" in response
    assert approved.screen.details.count("file.txt") == 1
    assert calls[-3:] == [
        "workspace.files.list", "workspace.files.list", "workspace.files.read",
    ]


def test_workspace_pack_confirmation_screen_is_cancel_by_default():
    from textual.app import App
    from isycode.tui_screens_approval import WorkspacePackConfirmScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(WorkspacePackConfirmScreen(
                "Files: 1\nEstimated tokens: ~100\nsource.py · 200 bytes"), results.append)

    async def run(action):
        async with Host().run_test() as pilot:
            await pilot.pause()
            await action(pilot)
            await pilot.pause()

    asyncio.run(run(lambda pilot: pilot.press("escape")))
    asyncio.run(run(lambda pilot: pilot.click("#workspace-pack-approve")))
    assert results == [False, True]
