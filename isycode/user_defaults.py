"""User-wide ISyCode defaults, stored independently from any workspace."""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from isycode.agent_loop import (
    AGENT_STEP_CHOICES, ANSWER_TOKEN_CHOICES, DEFAULT_AGENT_STEPS, DEFAULT_ANSWER_TOKENS,
)
from isycode.workspace_setup import state_root


class UserDefaultsStore:
    """Private defaults shared by every ISyCode workspace for this user.

    This store is for preferences only. It must never contain Workspace
    Authority grants, credentials, or workspace paths.
    """

    VERSION = 1
    MAX_BYTES = 64 * 1024
    NEW_WORKSPACE_CHOICES = {"ask", "temporary", "recurring"}
    # Mode preselected for a workspace opened for the first time. It is a
    # preference only: the chosen mode is saved in that workspace's Authority
    # policy, and "ask" shows the mode screen.
    NEW_WORKSPACE_MODES = {"ask", "classic", "security"}
    ROLE_KINDS = {"agents", "subagents", "motors"}

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or state_root()).expanduser()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError("ISyCode user settings directory is unsafe")
        self.directory = self.directory.resolve(strict=True)
        if os.name == "posix":
            self.directory.chmod(0o700)
        self.path = self.directory / "user-defaults.json"

    def load(self) -> dict[str, Any]:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return {"version": self.VERSION, "new_workspace": "ask",
                    "new_workspace_mode": "ask", "default_role": None,
                    "agent_steps": DEFAULT_AGENT_STEPS, "answer_tokens": DEFAULT_ANSWER_TOKENS}
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > self.MAX_BYTES:
            raise ValueError("ISyCode user settings file is unsafe")
        if os.name == "posix" and metadata.st_mode & 0o077:
            raise ValueError("ISyCode user settings file permissions are too open")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(self.path, flags)
        try:
            opened = os.fstat(descriptor)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != metadata.st_dev
                    or opened.st_ino != metadata.st_ino or opened.st_size > self.MAX_BYTES):
                raise ValueError("ISyCode user settings changed during inspection")
            content = os.read(descriptor, self.MAX_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(content) > self.MAX_BYTES:
            raise ValueError("ISyCode user settings exceed their size limit")
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict) or data.get("version") != self.VERSION:
            raise ValueError("ISyCode user settings are malformed")
        choice = data.get("new_workspace", "ask")
        mode = data.get("new_workspace_mode", "ask")
        if not isinstance(mode, str) or mode not in self.NEW_WORKSPACE_MODES:
            raise ValueError("ISyCode new workspace mode default is invalid")
        role = data.get("default_role")
        if not isinstance(choice, str) or choice not in self.NEW_WORKSPACE_CHOICES:
            raise ValueError("ISyCode new workspace default is invalid")
        if role is not None and (
                not isinstance(role, dict)
                or not isinstance(role.get("kind"), str)
                or role.get("kind") not in self.ROLE_KINDS
                or not isinstance(role.get("name"), str)
                or not 1 <= len(role["name"]) <= 120):
            raise ValueError("ISyCode default role is invalid")
        steps = data.get("agent_steps", DEFAULT_AGENT_STEPS)
        tokens = data.get("answer_tokens", DEFAULT_ANSWER_TOKENS)
        if type(steps) is not int or steps not in AGENT_STEP_CHOICES:
            raise ValueError("ISyCode agent step limit is invalid")
        if type(tokens) is not int or tokens not in ANSWER_TOKEN_CHOICES:
            raise ValueError("ISyCode answer length is invalid")
        return {"version": self.VERSION, "new_workspace": choice, "new_workspace_mode": mode,
                "default_role": role, "agent_steps": steps, "answer_tokens": tokens}

    def update(self, *, new_workspace: str | None = None,
               new_workspace_mode: str | None = None,
               default_role: dict[str, str] | None | object = ...,
               agent_steps: int | None = None, answer_tokens: int | None = None) -> None:
        current = self.load()
        if agent_steps is not None:
            if type(agent_steps) is not int or agent_steps not in AGENT_STEP_CHOICES:
                raise ValueError("ISyCode agent step limit is invalid")
            current["agent_steps"] = agent_steps
        if answer_tokens is not None:
            if type(answer_tokens) is not int or answer_tokens not in ANSWER_TOKEN_CHOICES:
                raise ValueError("ISyCode answer length is invalid")
            current["answer_tokens"] = answer_tokens
        if new_workspace is not None:
            if new_workspace not in self.NEW_WORKSPACE_CHOICES:
                raise ValueError("ISyCode new workspace default is invalid")
            current["new_workspace"] = new_workspace
        if new_workspace_mode is not None:
            if new_workspace_mode not in self.NEW_WORKSPACE_MODES:
                raise ValueError("ISyCode new workspace mode default is invalid")
            current["new_workspace_mode"] = new_workspace_mode
        if default_role is not ...:
            if default_role is not None and (
                    not isinstance(default_role, dict)
                    or not isinstance(default_role.get("kind"), str)
                    or default_role.get("kind") not in self.ROLE_KINDS
                    or not isinstance(default_role.get("name"), str)
                    or not 1 <= len(default_role["name"]) <= 120):
                raise ValueError("ISyCode default role is invalid")
            current["default_role"] = default_role
        payload = json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        temporary = self.directory / f".user-defaults-{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name == "posix":
                self.path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
