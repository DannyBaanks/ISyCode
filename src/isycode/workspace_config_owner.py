"""Owner-mediated workspace preferences, prompt commands, and safe initialization."""
from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.git_owner import GitOwner, git_executable
from isycode.prompt_expansion import (
    COMMAND_NAME_RE, MAX_COMMAND_BYTES, MAX_USER_COMMANDS, WORKSPACE_COMMANDS_DIR,
    CustomCommand, parse_command, read_result_text,
)
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_config import WorkspaceConfigResult, parse_workspace_config
from isycode.workspace_write import WritePreview, WorkspaceWriteOwner

_BEGIN = "# >>> ISYCODE managed block >>>"
_END = "# <<< ISYCODE managed block <<<"
_BLOCK = f"{_BEGIN}\n.isycode/\n{_END}"


@dataclass(frozen=True)
class ConfigInitialization:
    previews: tuple[WritePreview, ...]
    message: str = ""


class WorkspaceConfigOwner:
    """Coordinates narrow owners; this class itself performs no filesystem I/O."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.reader = LocalWorkspaceReadOwner(self.root, authority, owner_id="workspace_config")
        self.legacy_reader = LocalWorkspaceReadOwner(self.root, authority)
        self.writer = WorkspaceWriteOwner(self.root, authority, approvals,
                                          owner_id="workspace_config")
        self.git = GitOwner(self.root, authority, approvals)

    def _has_workspace_marker(self) -> bool:
        try:
            info = (self.root / ".isyroot").lstat()
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and info.st_size == 0

    def read_config(self) -> tuple[WorkspaceConfigResult | None, str]:
        if not self._has_workspace_marker():
            return None, "workspace config requires this folder's own .isyroot marker"
        outcome = self.reader.execute("workspace.config.read", {"path": ".isycode/config.json"})
        if outcome.decision == "ERROR" and "No such file" in outcome.reason:
            return None, ""
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return None, outcome.reason or "workspace settings could not be read"
        try:
            payload = json.loads(outcome.text)["text"].encode("utf-8")
        except (ValueError, KeyError, TypeError):
            return None, "workspace config read result was malformed"
        return parse_workspace_config(payload), ""

    def commands(self) -> tuple[dict[str, CustomCommand], str]:
        if not self._has_workspace_marker():
            return {}, "workspace commands require this folder's own .isyroot marker"
        listed = self.reader.execute("workspace.config.list", {"path": ".isycode/commands"})
        if listed.decision == "ERROR" and "No such file" in listed.reason:
            return {}, ""
        if listed.decision != "ALLOW" or listed.receipt is None:
            return {}, listed.reason or "workspace commands could not be listed"
        try:
            entries = json.loads(listed.text)["entries"]
        except (ValueError, KeyError, TypeError):
            return {}, "workspace command list was malformed"
        result: dict[str, CustomCommand] = {}
        for item in entries[:MAX_USER_COMMANDS]:
            name = item.get("name", "")
            if item.get("kind") != "file" or not name.endswith(".md"):
                continue
            path = f".isycode/commands/{name}"
            read = self.reader.execute("workspace.config.read", {"path": path})
            if read.decision != "ALLOW" or read.receipt is None:
                continue
            text = read_result_text(read.text)
            if len(text.encode("utf-8")) > MAX_COMMAND_BYTES:
                continue
            command = parse_command(Path(name).stem.lower(), text, "workspace")
            if command is not None:
                result[command.name] = command
        return result, ""

    def preview_update(self, values: dict[str, Any]) -> WritePreview:
        """Prepare one reviewed update to supported non-security preferences."""
        if not self._has_workspace_marker():
            raise ValueError("workspace config requires this folder's own .isyroot marker")
        current, issue = self.read_config()
        if issue:
            raise ValueError(issue)
        if current is None:
            raise ValueError("initialize .isycode/ before saving workspace preferences")
        if not current.valid:
            raise ValueError(f"existing workspace config is invalid: {current.error}")
        merged = {**current.values, **values}
        payload = {"version": 1, **merged}
        validated = parse_workspace_config(json.dumps(payload).encode("utf-8"))
        if not validated.valid:
            raise ValueError(validated.error)
        return self.writer.preview(".isycode/config.json",
                                   json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def legacy_commands(self) -> tuple[list[str], str]:
        listed = self.legacy_reader.execute(
            "workspace.files.list", {"path": WORKSPACE_COMMANDS_DIR})
        if listed.decision != "ALLOW" or listed.receipt is None:
            return [], listed.reason or "legacy workspace commands could not be listed"
        try:
            entries = json.loads(listed.text)["entries"]
        except (ValueError, KeyError, TypeError):
            return [], "legacy workspace command list was malformed"
        names = sorted({Path(item.get("name", "")).stem for item in entries
                        if item.get("kind") == "file"
                        and item.get("name", "").endswith(".md")
                        and COMMAND_NAME_RE.fullmatch(Path(item["name"]).stem)},
                       key=str.casefold)
        return names[:MAX_USER_COMMANDS], ""

    def preview_migrate_legacy(self, name: str) -> WritePreview:
        if not self._has_workspace_marker():
            raise ValueError("migration requires this folder's own .isyroot marker")
        if not isinstance(name, str) or not COMMAND_NAME_RE.fullmatch(name):
            raise ValueError("invalid workspace command name")
        destination = f".isycode/commands/{name}.md"
        existing = self.reader.execute("workspace.config.read", {"path": destination})
        if existing.decision == "ALLOW" and existing.receipt is not None:
            raise ValueError("a command with this name already exists in .isycode/commands")
        if existing.decision != "ERROR" or "No such file" not in existing.reason:
            raise ValueError(existing.reason or "destination could not be proven absent")
        source = self.legacy_reader.execute(
            "workspace.files.read", {"path": f"{WORKSPACE_COMMANDS_DIR}/{name}.md"})
        if source.decision != "ALLOW" or source.receipt is None:
            raise ValueError(source.reason or "legacy command could not be read")
        try:
            text = read_result_text(source.text)
        except (ValueError, TypeError) as exc:
            raise ValueError("legacy command contents are malformed") from exc
        if len(text.encode("utf-8")) > MAX_COMMAND_BYTES or parse_command(name, text, "workspace") is None:
            raise ValueError("legacy command is invalid or exceeds 32 KiB")
        return self.writer.preview(destination, text)

    def prepare_initialization(self) -> ConfigInitialization:
        if not self._has_workspace_marker():
            return ConfigInitialization((), "This folder has no .isyroot workspace marker.")

        git_note = ""
        install_ignore = False
        try:
            git_entry_exists = (self.root / ".git").lstat() is not None
        except FileNotFoundError:
            git_entry_exists = False
        except OSError:
            git_entry_exists = True
        if git_executable() is None or not git_entry_exists:
            git_note = "Git ignore could not be installed because this folder is not a Git repository or Git is unavailable."
        else:
            tracked = self.git.is_path_tracked(".isycode")
            if tracked.decision != "ALLOW" or tracked.receipt is None:
                return ConfigInitialization((),
                    f"Git could not prove that .isycode/ is untracked: {tracked.reason[:180]}")
            if json.loads(tracked.text).get("tracked"):
                return ConfigInitialization((),
                    ".isycode/ already contains tracked files; remove them from Git manually before initialization.")
            install_ignore = True

        previews: list[WritePreview] = []
        if install_ignore:
            ignore_read = self.reader.execute("workspace.config.read", {"path": ".gitignore"})
            if ignore_read.decision == "ALLOW" and ignore_read.receipt is not None:
                try:
                    current = json.loads(ignore_read.text)["text"]
                except (ValueError, KeyError, TypeError):
                    return ConfigInitialization((), ".gitignore could not be read safely.")
            elif ignore_read.decision == "ERROR" and "No such file" in ignore_read.reason:
                current = ""
            else:
                return ConfigInitialization((),
                    f"Cannot safely update .gitignore: {ignore_read.reason[:180]}")
            updated, problem = _managed_ignore(current)
            if problem:
                return ConfigInitialization((), problem)
            if updated is not None:
                try:
                    previews.append(self.writer.preview(".gitignore", updated))
                except (OSError, ValueError) as exc:
                    return ConfigInitialization((), f"Cannot prepare .gitignore: {str(exc)[:180]}")
        existing, issue = self.read_config()
        if issue:
            return ConfigInitialization((), f"Cannot safely inspect workspace config: {issue[:180]}")
        if existing is None:
            try:
                previews.append(self.writer.preview(".isycode/config.json", '{"version":1}\n',
                                                     create_commands_folder=True))
            except (OSError, ValueError) as exc:
                return ConfigInitialization((), f"Cannot prepare workspace config: {str(exc)[:180]}")
        elif not existing.valid:
            return ConfigInitialization((),
                f"Existing workspace config is invalid and was left untouched: {existing.error}")
        if not previews:
            return ConfigInitialization((), "Workspace config is already initialized." +
                                        (f" {git_note}" if git_note else ""))
        return ConfigInitialization(tuple(previews), git_note)

    def apply(self, preview: WritePreview, approval: ActionApproval | None):
        return self.writer.apply(preview, approval)


def _managed_ignore(current: str) -> tuple[str | None, str]:
    if not isinstance(current, str):
        return None, ".gitignore is not valid UTF-8 text."
    starts, ends = current.count(_BEGIN), current.count(_END)
    if starts != ends or starts > 1:
        return None, ".gitignore has a malformed or duplicate ISyCode managed block; it was left untouched."
    lines = current.splitlines()
    if starts == 1:
        begin = lines.index(_BEGIN)
        end = lines.index(_END)
        if end != begin + 2 or lines[begin + 1] != ".isycode/":
            return None, ".gitignore has a malformed ISyCode managed block; it was left untouched."
        return None, ""
    if any(line.strip() == ".isycode/" for line in lines):
        return None, ""
    if not current:
        return _BLOCK + "\n", ""
    newline = "\r\n" if "\r\n" in current else "\n"
    prefix = current if current.endswith(("\n", "\r")) else current + newline
    block = _BLOCK.replace("\n", newline)
    return prefix + block + newline, ""


__all__ = ["ConfigInitialization", "WorkspaceConfigOwner"]
