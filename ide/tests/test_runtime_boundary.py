import asyncio
import os
from pathlib import Path

import pytest

from core.runtime import RuntimeRegistry, ToolCall


def run_tool(root: Path, name: str, arguments: dict):
    runtime = RuntimeRegistry(root).get_available()[0]
    selected = RuntimeRegistry(root).get(runtime)
    return asyncio.run(selected.execute(ToolCall(name, arguments, "test")))


def test_relative_read_and_write(tmp_path):
    result = run_tool(tmp_path, "write", {"path": "hello.py", "content": "hello"})
    assert result.success
    result = run_tool(tmp_path, "read", {"path": "hello.py"})
    assert result.success
    assert result.stdout == "hello"


def test_absolute_path_inside_workspace_is_allowed(tmp_path):
    target = (tmp_path / "nested" / "hello.py").resolve()
    result = run_tool(tmp_path, "write", {"path": str(target), "content": "ok"})
    assert result.success
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize("path", ["../outside.py", "nested/../../outside.py"])
def test_parent_traversal_is_rejected(tmp_path, path):
    result = run_tool(tmp_path, "write", {"path": path, "content": "escape"})
    assert not result.success
    assert result.error_code == "PATH_OUTSIDE_WORKSPACE"


def test_absolute_path_outside_workspace_is_rejected(tmp_path):
    outside = (tmp_path.parent / "outside.py").resolve()
    result = run_tool(tmp_path, "write", {"path": str(outside), "content": "escape"})
    assert not result.success
    assert result.error_code == "PATH_OUTSIDE_WORKSPACE"
    assert not outside.exists()


def test_nonexistent_read_is_structured_error(tmp_path):
    result = run_tool(tmp_path, "read", {"path": "missing.py"})
    assert not result.success
    assert result.error_code == "FILE_NOT_FOUND"
    assert result.stderr


def test_workspace_root_is_not_a_file(tmp_path):
    result = run_tool(tmp_path, "read", {"path": "."})
    assert not result.success
    assert result.error_code == "PATH_IS_WORKSPACE_ROOT"


def test_glob_traversal_is_rejected(tmp_path):
    result = run_tool(tmp_path, "glob", {"pattern": "../*"})
    assert not result.success
    assert result.error_code == "PATH_OUTSIDE_WORKSPACE"


def test_symlink_escape_is_rejected_when_supported(tmp_path):
    outside = tmp_path.parent / "isyvm-symlink-outside.py"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        outside.unlink(missing_ok=True)
        pytest.skip("symlinks unavailable on this platform")
    result = run_tool(tmp_path, "write", {"path": str(link), "content": "escape"})
    outside.unlink(missing_ok=True)
    assert not result.success
    assert result.error_code == "PATH_OUTSIDE_WORKSPACE"
