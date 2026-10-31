"""One predicate for whether this machine can run the command sandbox.

These tests used to ask for the operating system, which is the wrong question:
bubblewrap, libseccomp and /usr/bin/python3 exist on Linux, so a macOS box
answers "posix" to the OS test and then cannot prepare a single command.
"""
from __future__ import annotations

import pytest

from isycode.command_runner import sandbox_executable

REASON = ("NOT_DEMONSTRATED: the command sandbox needs bubblewrap, libseccomp and "
          "python3; a POSIX system without them, such as macOS, keeps commands "
          "disabled and has no unsandboxed fallback")


def sandbox_missing() -> bool:
    """Whether no sandboxed command request can be built here."""
    return sandbox_executable() is None


requires_sandbox = pytest.mark.skipif(sandbox_missing(), reason=REASON)
