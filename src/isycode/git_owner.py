"""Git status, diff and commit for the workspace repository behind Authority and IsySentinel.

Running git on a repository can start programs the repository itself
configures: fsmonitor, filters, pagers, textconv and external diff drivers,
credential helpers and hooks. This owner refuses any repository whose local
config defines one, disables hooks for commits, ignores the system config,
and hides the same sensitive paths the chat file tools refuse. Only a
``.git`` folder at the workspace root is supported, so git never walks up
past ``.isyroot`` into a parent repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from isycode.action_runtime import (
    COMMAND_SYSTEM_BIN_DIRS, GIT_MAX_COMMIT_PATHS, GIT_MAX_MESSAGE_CHARS, ActionOutcome,
    ActionReceipt, ProductActionGate, WorkspaceReadSystembility, command_relative_path_valid,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

OWNER_ID = "workspace_git"
MAX_GIT_OUTPUT = 256 * 1024
GIT_TIMEOUT_S = 30
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_UNTRACKED_PREVIEW = 50

# Local config keys that make git run a program or reach elsewhere. Not listed:
# extensions.worktreeConfig, which only enables .git/config.worktree (git sets it
# for worktrees and sparse checkouts); that file is checked with this same list.
_DANGEROUS_KEYS = re.compile(
    r"^(core\.(fsmonitor|hookspath|pager|editor|sshcommand|askpass|gitproxy|worktree"
    r"|alternaterefscommand)"
    r"|sequence\.editor|diff\.external|gpg\..*|credential\..*|include\..*|includeif\..*"
    r"|filter\..*|pager\..*|diff\..+\.(command|textconv)|merge\..+\.driver"
    r"|remote\..+\.(uploadpack|receivepack|vcs)|uploadpack\..*|receive\..*)$")
_SAFE_OVERRIDES = (
    "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
    "-c", "diff.external=", "-c", "credential.helper=", "-c", "protocol.allow=never",
    "-c", "color.ui=false", "-c", "core.quotepath=false",
)

GIT_TOOLS = [
    {"type": "function", "function": {
        "name": "git_status",
        "description": "Show the git branch and changed files of the workspace repository.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "git_diff",
        "description": "Show the git diff of the workspace (unstaged by default, or staged).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file or folder; defaults to everything."},
            "staged": {"type": "boolean", "description": "Show staged changes instead of unstaged ones."},
        }, "additionalProperties": False},
    }},
]
GIT_COMMIT_TOOL = {"type": "function", "function": {
    "name": "git_commit",
    "description": ("Propose a git commit. The user reviews the exact diff and message and must "
                    "approve it. Hooks do not run and nothing is pushed."),
    "parameters": {"type": "object", "properties": {
        "message": {"type": "string", "description": "Commit message."},
        "paths": {"type": "array", "items": {"type": "string"},
                  "description": "Workspace-relative files to commit; defaults to every changed file."},
    }, "required": ["message"], "additionalProperties": False},
}}
GIT_TOOL_NAMES = frozenset({"git_status", "git_diff", "git_commit"})


def git_executable() -> str | None:
    for folder in COMMAND_SYSTEM_BIN_DIRS:
        candidate = Path(folder) / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _sensitive_excludes() -> list[str]:
    names = (".git", ".isycode", ".ssh", ".aws", ".gnupg", ".env", "id_rsa", "id_ed25519",
             "credentials", "secrets.json")
    patterns = [f":(exclude,glob){prefix}{name}{suffix}" for name in names
                for prefix in ("", "**/") for suffix in ("", "/**")]
    patterns += [f":(exclude,glob){prefix}{glob}" for glob in
                 (".env.*", "*.pem", "*.key", "*.p12", "*.pfx") for prefix in ("", "**/")]
    return patterns


def _sensitive(path: str) -> bool:
    return any(WorkspaceReadSystembility.is_sensitive_name(part) for part in path.split("/"))


@dataclass(frozen=True)
class CommitPreview:
    request: ActionRequest
    message: str
    paths: tuple[str, ...]
    diff: str


class GitOwner:
    """The only execution owner for git.status, git.diff and git.commit."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore | None = None):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)

    # ── repository checks and process ────────────────────────────

    def _repository_problem(self) -> str | None:
        git_dir = self.root / ".git"
        try:
            info = git_dir.lstat()
        except FileNotFoundError:
            return "this workspace is not a git repository (no .git folder at its root)"
        if not stat.S_ISDIR(info.st_mode):
            return "only a .git folder at the workspace root is supported (not a worktree link)"
        git = git_executable()
        if git is None:
            return "git is not installed in a system bin folder"
        for name in ("config", "config.worktree"):
            config = git_dir / name
            if not config.exists():
                continue
            if config.is_symlink() or not config.is_file():
                return f".git/{name} is not a regular file"
            result = self._raw([git, "config", "--file", str(config), "--no-includes",
                                "--list", "--name-only", "-z"])
            if result is None or result[0] != 0:
                return f".git/{name} could not be read safely"
            keys = [key.casefold() for key in result[1].decode("utf-8", "replace").split("\0") if key]
            flagged = sorted({key for key in keys if _DANGEROUS_KEYS.match(key)})
            if flagged:
                return ("the repository config defines programs git would run ("
                        + ", ".join(flagged[:5]) + "); ISyCode will not run git here")
        return None

    def _environment(self) -> dict[str, str]:
        env = {"PATH": ":".join(COMMAND_SYSTEM_BIN_DIRS), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "GIT_DIR": str(self.root / ".git"), "GIT_WORK_TREE": str(self.root),
               "GIT_CEILING_DIRECTORIES": str(self.root.parent), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat",
               "GIT_EDITOR": "true", "GIT_NO_REPLACE_OBJECTS": "1"}
        # The user's own global config supplies the commit identity.
        if os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
        return env

    def _raw(self, argv: list[str]) -> tuple[int, bytes, bool] | None:
        try:
            done = subprocess.run(argv, cwd=self.root, env=self._environment(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=GIT_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        data = done.stdout
        return done.returncode, data[:MAX_GIT_OUTPUT], len(data) > MAX_GIT_OUTPUT

    def _git(self, *args: str, ok_codes: tuple[int, ...] = (0,)) -> tuple[str, bool]:
        git = git_executable()
        if git is None:
            raise ValueError("git is not installed in a system bin folder")
        result = self._raw([git, *_SAFE_OVERRIDES, *args])
        if result is None:
            raise ValueError("git did not finish in time")
        code, data, truncated = result
        text = data.decode("utf-8", "replace")
        if code not in ok_codes and not truncated:
            raise ValueError(f"git {args[0]} failed: {text.strip()[:300]}")
        return text, truncated

    def _request(self, action_id: str, **extra) -> ActionRequest:
        return ActionRequest(action_id, self.root, str(self.root),
                             {"git": git_executable() or "", "workspace_root": str(self.root), **extra},
                             execution_owner="workspace_git")

    def _finish(self, request: ActionRequest, result: dict) -> ActionOutcome:
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                                "ALLOW", "SUCCESS", hashlib.sha256(text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, text):
            return ActionOutcome("Git receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Git receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt, f"{request.action_id} completed")

    def _authorize(self, request: ActionRequest, approval: ActionApproval | None = None) -> str | None:
        problem = self._repository_problem()
        if problem:
            return problem
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            return "; ".join(check.reason for check in decision.checks if not check.passed)
        return None

    # ── read actions ─────────────────────────────────────────────

    def _status_entries(self) -> tuple[str, list[dict[str, str]]]:
        text, _ = self._git("status", "--porcelain=v1", "-z", "-b", "--untracked-files=all",
                            "--", ".", *_sensitive_excludes())
        fields = text.split("\0")
        branch = ""
        entries: list[dict[str, str]] = []
        index = 0
        while index < len(fields):
            field = fields[index]
            index += 1
            if not field:
                continue
            if field.startswith("## "):
                branch = field[3:]
                continue
            code, path = field[:2], field[3:]
            entry = {"status": code, "path": path}
            if code[0] in "RC" and index < len(fields):
                entry["from"] = fields[index]
                index += 1
            if not _sensitive(path):
                entries.append(entry)
        return branch, entries

    def status(self) -> ActionOutcome:
        try:
            request = self._request("git.status")
        except (TypeError, ValueError):
            return ActionOutcome("Git status denied.", "DENY", None, "invalid git request")
        reason = self._authorize(request)
        if reason:
            return ActionOutcome("Git status denied.", "DENY", None, reason)
        try:
            branch, entries = self._status_entries()
        except ValueError as exc:
            return ActionOutcome("Git status failed.", "ERROR", None, str(exc)[:300])
        return self._finish(request, {"branch": branch, "changes": entries,
                                      "clean": not entries})

    def is_path_tracked(self, path: str) -> ActionOutcome:
        """Prove whether the reserved workspace config tree is present in the index."""
        if path != ".isycode":
            return ActionOutcome("Git path inspection denied.", "DENY", None,
                                 "only .isycode can be inspected")
        request = self._request("git.status", inspect_path=".isycode")
        reason = self._authorize(request)
        if reason:
            return ActionOutcome("Git path inspection denied.", "DENY", None, reason)
        try:
            output, truncated = self._git("ls-files", "--cached", "-z", "--", ".isycode")
        except ValueError as exc:
            return ActionOutcome("Git path inspection failed.", "ERROR", None, str(exc)[:300])
        if truncated:
            return ActionOutcome("Git path inspection failed.", "ERROR", None,
                                 "Git output exceeded the inspection limit")
        paths = sorted(item for item in output.split("\0") if item)
        return self._finish(request, {"path": ".isycode", "tracked": bool(paths),
                                      "tracked_paths": paths})

    def diff(self, path: str = ".", staged: bool = False) -> ActionOutcome:
        path = (path or ".").removeprefix("./").rstrip("/") or "."
        try:
            request = self._request("git.diff", staged=bool(staged), path=path)
        except (TypeError, ValueError):
            return ActionOutcome("Git diff denied.", "DENY", None, "invalid git request")
        reason = self._authorize(request)
        if reason:
            return ActionOutcome("Git diff denied.", "DENY", None, reason)
        try:
            text, truncated = self._git(
                "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                *(["--cached"] if staged else []), "--", path, *_sensitive_excludes())
        except ValueError as exc:
            return ActionOutcome("Git diff failed.", "ERROR", None, str(exc)[:300])
        return self._finish(request, {"path": path, "staged": bool(staged), "diff": text,
                                      "truncated": truncated})

    # ── commit ───────────────────────────────────────────────────

    def _commit_diff(self, paths: tuple[str, ...]) -> str:
        head, _ = self._git("rev-parse", "--verify", "--quiet", "HEAD", ok_codes=(0, 1))
        base = head.strip() or EMPTY_TREE
        _, entries = self._status_entries()
        untracked = {entry["path"] for entry in entries if entry["status"] == "??"}
        tracked = [path for path in paths if path not in untracked]
        parts = []
        if tracked:
            text, truncated = self._git("diff", "--no-ext-diff", "--no-textconv", "--no-color",
                                        base, "--", *tracked)
            if truncated:
                raise ValueError("the change is too large to review in one commit")
            parts.append(text)
        new_files = [path for path in paths if path in untracked]
        if len(new_files) > MAX_UNTRACKED_PREVIEW:
            raise ValueError(f"more than {MAX_UNTRACKED_PREVIEW} new files; commit them in smaller groups")
        for path in new_files:
            text, truncated = self._git("diff", "--no-index", "--no-ext-diff", "--no-textconv",
                                        "--no-color", "--", "/dev/null", path, ok_codes=(0, 1))
            if truncated:
                raise ValueError(f"{path} is too large to review")
            parts.append(text)
        return "".join(parts)

    def preview_commit(self, message: str, paths: list[str] | tuple[str, ...] | None = None) -> CommitPreview:
        """Build the reviewed commit. Raises ValueError when there is nothing safe to commit."""
        if not isinstance(message, str) or not message.strip() or len(message) > GIT_MAX_MESSAGE_CHARS:
            raise ValueError(f"the commit message must have 1–{GIT_MAX_MESSAGE_CHARS} characters")
        problem = self._repository_problem()
        if problem:
            raise ValueError(problem)
        _, entries = self._status_entries()
        changed = set()
        for entry in entries:
            changed.add(entry["path"])
            if "from" in entry:
                changed.add(entry["from"])
        if paths is None:
            selected = tuple(sorted(changed))
        else:
            if not isinstance(paths, (list, tuple)) or not all(isinstance(p, str) for p in paths):
                raise ValueError("paths must be a list of workspace-relative files")
            selected = tuple(sorted({p.removeprefix("./") for p in paths}))
        if not selected:
            raise ValueError("there are no changes to commit")
        if len(selected) > GIT_MAX_COMMIT_PATHS:
            raise ValueError(f"at most {GIT_MAX_COMMIT_PATHS} files per commit")
        for path in selected:
            if not command_relative_path_valid(path):
                raise ValueError(f"{path} cannot be committed (sensitive or outside the workspace)")
            if path not in changed:
                raise ValueError(f"{path} has no changes to commit")
        diff = self._commit_diff(selected)
        digest = hashlib.sha256(json.dumps([message, selected, diff]).encode("utf-8")).hexdigest()
        request = self._request("git.commit", message=message, paths=selected, diff_sha256=digest)
        return CommitPreview(request, message, selected, diff)

    def commit(self, preview: CommitPreview, approval: ActionApproval | None) -> ActionOutcome:
        request = preview.request
        try:
            current = self._commit_diff(preview.paths)
        except ValueError as exc:
            return ActionOutcome("Commit denied.", "DENY", None, str(exc)[:300])
        digest = hashlib.sha256(json.dumps([preview.message, preview.paths, current])
                                .encode("utf-8")).hexdigest()
        if digest != request.parameters["diff_sha256"]:
            return ActionOutcome("Commit denied.", "DENY", None,
                                 "the files changed after review; nothing was committed")
        reason = self._authorize(request, approval)
        if reason:
            return ActionOutcome("Commit denied.", "DENY", None, reason)
        try:
            self._git("add", "-A", "--", *preview.paths)
            self._git("commit", "--no-verify", "--no-edit", "-m", preview.message,
                      "--", *preview.paths)
            commit_id, _ = self._git("rev-parse", "HEAD")
        except ValueError as exc:
            return ActionOutcome("Commit failed.", "ERROR", None, str(exc)[:300])
        return self._finish(request, {"commit": commit_id.strip(), "paths": list(preview.paths),
                                      "message": preview.message})


__all__ = ["GIT_COMMIT_TOOL", "GIT_TOOLS", "GIT_TOOL_NAMES", "CommitPreview", "GitOwner",
           "git_executable"]
