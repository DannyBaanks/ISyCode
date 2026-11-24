"""Flow host commands: the resolved program must be the one argv[0] named.

``CommandRunOwner.prepare`` resolves ``argv[0]`` through ``PATH`` and leaves the
reviewed argv untouched, so on Windows ``powershell`` arrives at the boundary as
``C:\\...\\powershell.EXE``. The boundary has to accept exactly that difference —
the suffix the lookup added, in the case the filesystem stored — and nothing else.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from isycode.action_runtime import (
    COMMAND_MAX_OUTPUT_BYTES,
    CommandProcessSystembility,
    host_program_name_matches,
)
from isycode.command_runner import masked_digest
from isycode.security import ActionRequest, AuthorityDecision


def flow_request(root: Path, program: str, argv: tuple[str, ...]) -> ActionRequest:
    return ActionRequest(
        "workspace.command.run", root, program,
        {"argv": argv, "program": program, "cwd": str(root), "timeout_s": 30,
         "network": "host", "host_execution": True, "executable": program,
         "workspace_root": str(root), "masked_sha256": masked_digest(()),
         "masked_count": 0, "max_output_bytes": COMMAND_MAX_OUTPUT_BYTES},
        execution_owner="workspace_command")


def flow_decision(request: ActionRequest) -> AuthorityDecision:
    return AuthorityDecision(True, "grant:flow:workspace.command.run",
                             "Flow computer-wide grant matched", request.digest)


@pytest.fixture
def windows_extensions(monkeypatch):
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")


@pytest.mark.parametrize(("program", "argv0"), [
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", "powershell"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", "PowerShell"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", "powershell.exe"),
    (r"C:\Tools\npm.CMD", "npm"),
    (r"C:\Tools\run", "run"),
])
def test_the_suffix_a_windows_lookup_appends_is_the_same_program(program, argv0,
                                                                windows_extensions):
    assert host_program_name_matches(program, argv0, platform="nt")


@pytest.mark.parametrize(("program", "argv0"), [
    (r"C:\Windows\System32\cmd.exe", "powershell"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", "powershell.ps1"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", "power"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE", ""),
])
def test_a_different_program_is_still_refused(program, argv0, windows_extensions):
    assert not host_program_name_matches(program, argv0, platform="nt")


def test_pathext_decides_which_suffix_is_the_same_program(monkeypatch):
    monkeypatch.setenv("PATHEXT", ".COM;.EXE")
    assert host_program_name_matches(r"C:\Tools\build.EXE", "build", platform="nt")
    assert not host_program_name_matches(r"C:\Tools\build.CMD", "build", platform="nt")


def test_posix_keeps_the_exact_name_comparison():
    assert host_program_name_matches("/usr/bin/echo", "echo", platform="posix")
    assert not host_program_name_matches("/usr/bin/echo", "echo.exe", platform="posix")
    assert not host_program_name_matches("/usr/bin/printf", "echo", platform="posix")


@pytest.mark.parametrize("value", [None, 1, b"powershell", ["powershell"], ""])
def test_only_strings_can_match(value):
    assert not host_program_name_matches(value, "powershell", platform="nt")
    assert not host_program_name_matches("C:\\Tools\\powershell.EXE", value, platform="nt")


@pytest.mark.skipif(os.name != "nt", reason="PATH appends PATHEXT only on Windows")
def test_flow_boundary_accepts_the_name_the_path_lookup_resolved(tmp_path):
    python = Path(sys.executable).resolve()
    request = flow_request(tmp_path, str(python), (python.stem, "--version"))

    result = CommandProcessSystembility().evaluate(request, flow_decision(request))

    assert result.passed, result.reason


@pytest.mark.skipif(os.name != "nt", reason="PATH appends PATHEXT only on Windows")
def test_flow_boundary_still_refuses_a_request_naming_another_program(tmp_path):
    python = Path(sys.executable).resolve()
    request = flow_request(tmp_path, str(python), ("definitely-not-python", "--version"))

    result = CommandProcessSystembility().evaluate(request, flow_decision(request))

    assert not result.passed
    assert "existing executable" in result.reason
