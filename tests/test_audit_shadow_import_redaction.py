"""Regressions from the 2026-10-08 Hermes audit (findings 1 and 3)."""
import subprocess
import sys

from isycode.chat_sessions import ChatSessionStore
from isycode.command_runner import PYTHON, command_bootstrap, sandbox_command


def test_command_bootstrap_runs_isolated_from_workspace_modules(tmp_path):
    args = sandbox_command("/usr/bin/bwrap", tmp_path, "/usr/bin/true", ("true",), ".", (), timeout_s=5)
    at = args.index(PYTHON)
    assert args[at + 1:at + 3] == ["-I", "-c"]
    # The same flags, run for real from a folder that shadows a stdlib module the
    # bootstrap imports: the workspace copy must not run before the limits do.
    (tmp_path / "resource.py").write_text("raise SystemExit('SHADOWED')\n")
    run = subprocess.run([sys.executable, "-I", "-c", command_bootstrap(5), "/usr/bin/true"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert "SHADOWED" not in run.stderr + run.stdout
    # Control: without -I the shadow does run, so the check above is meaningful.
    bare = subprocess.run([sys.executable, "-c", command_bootstrap(5), "/usr/bin/true"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert "SHADOWED" in bare.stderr


def test_session_redaction_covers_single_quoted_keys():
    text = "{'api_key': 'sk-proj-SYNTHETIC1234', 'password': 'hunter2-synthetic'}"
    clean = ChatSessionStore._sanitize_text(text)
    assert "SYNTHETIC1234" not in clean and "hunter2" not in clean
    assert ChatSessionStore._sanitize_text('{"password": "x-synthetic"}').count("x-synthetic") == 0
