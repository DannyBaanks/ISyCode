"""Approved, diff-previewed changes to one UTF-8 text file inside the workspace.

The model may only *propose* a change: the complete new content of a file
(`workspace_write`) or one exact text fragment to replace (`workspace_edit`).
The owner turns that into an exact unified diff and an ActionRequest bound to
the digests of the current and proposed content and to any new folders.
Nothing is written until Workspace Authority (path-scoped grant plus a fresh
one-use approval) and IsySentinel allow that exact request; the file is then
replaced atomically through directory handles that never follow symlinks,
re-read, checkpointed for undo, and journaled with a receipt.

Undo (`workspace.files.restore`) is its own approved action: it puts back the
content from before one change, or removes a file that change created, and
refuses if the file was modified after that change.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isycode.action_runtime import (
    CONFIG_MAX_BYTES, CONFIG_OWNER_ID, MAX_MOVE_BYTES, MAX_WRITE_BYTES,
    WRITE_PROTECTED_NAMES, ActionOutcome, ActionReceipt, ProductActionGate,
    WorkspaceReadSystembility, workspace_config_path_allowed,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import state_root
from isycode.winfs import VerifiedFS, is_link, use_verified_fs

MAX_NEW_FOLDERS = 8
MAX_CHECKPOINTS = 50
CHECKPOINT_ID = re.compile(r"ckpt_[0-9]{13}_[0-9a-f]{8}")

WRITE_TOOL_NAME = "workspace_write"
WRITE_TOOL = {"type": "function", "function": {
    "name": WRITE_TOOL_NAME,
    "description": ("Propose replacing one UTF-8 text file (up to 128 KiB) in the workspace with "
                    "the complete new content, or creating it (missing folders are created). "
                    "Prefer workspace_edit for changes to existing files. The user reviews the "
                    "exact diff and must approve; the result says whether it was written."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "content": {"type": "string", "description": "The complete new file content."},
    }, "required": ["path", "content"], "additionalProperties": False},
}}
EDIT_TOOL_NAME = "workspace_edit"
EDIT_TOOL = {"type": "function", "function": {
    "name": EDIT_TOOL_NAME,
    "description": ("Propose replacing an exact text fragment in one existing UTF-8 file. "
                    "old_text must appear exactly once unless replace_all is true; include "
                    "enough surrounding lines to make it unique. The user reviews the diff "
                    "and must approve."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "old_text": {"type": "string", "description": "Exact current text to replace."},
        "new_text": {"type": "string", "description": "Replacement text."},
        "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
    }, "required": ["path", "old_text", "new_text"], "additionalProperties": False},
}}

DELETE_TOOL_NAME = "workspace_delete"
DELETE_TOOL = {"type": "function", "function": {
    "name": DELETE_TOOL_NAME,
    "description": ("Propose deleting one UTF-8 text file (up to 128 KiB) in the workspace. The "
                    "user sees the full content being removed and must approve; /undo restores it."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
    }, "required": ["path"], "additionalProperties": False},
}}
MOVE_TOOL_NAME = "workspace_move"
MOVE_TOOL = {"type": "function", "function": {
    "name": MOVE_TOOL_NAME,
    "description": ("Propose moving or renaming one file (up to 16 MiB) inside the workspace. "
                    "The destination must not exist; missing folders are created. The user "
                    "must approve; /undo moves it back."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Current workspace-relative file path."},
        "to": {"type": "string", "description": "New workspace-relative file path."},
    }, "required": ["path", "to"], "additionalProperties": False},
}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class WritePreview:
    request: ActionRequest
    path: str
    diff: str
    created: bool
    content: str = field(repr=False)
    removes: bool = False
    destination: str = ""

    @property
    def is_undo(self) -> bool:
        return (self.request.action_id == "workspace.files.restore"
                or bool(self.request.parameters.get("undo_of")))

    @property
    def kind(self) -> str:
        return self.request.action_id.rsplit(".", 1)[-1]


class CheckpointStore:
    """Private per-workspace history of pre-change content, outside the checkout."""

    def __init__(self, root: Path, directory: Path | None = None):
        root_id = _sha(str(root).encode("utf-8"))[:32]
        base = Path(directory or (state_root() / "checkpoints")).expanduser()
        self.directory = base / root_id

    def _ensure(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise OSError("checkpoint directory is unsafe")
        if os.name == "posix":
            self.directory.chmod(0o700)
        return self.directory

    def save(self, record: dict[str, Any]) -> str:
        directory = self._ensure()
        checkpoint_id = f"ckpt_{int(time.time() * 1000):013d}_{secrets.token_hex(4)}"
        payload = json.dumps({**record, "id": checkpoint_id, "undone": False},
                             ensure_ascii=False).encode("utf-8")
        temporary = directory / f".{checkpoint_id}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / f"{checkpoint_id}.json")
        finally:
            if temporary.exists():
                temporary.unlink()
        for old in sorted(directory.glob("ckpt_*.json"))[:-MAX_CHECKPOINTS]:
            old.unlink(missing_ok=True)
        return checkpoint_id

    def load(self, checkpoint_id: str) -> dict[str, Any]:
        if not isinstance(checkpoint_id, str) or not CHECKPOINT_ID.fullmatch(checkpoint_id):
            raise ValueError("invalid checkpoint id")
        path = self.directory / f"{checkpoint_id}.json"
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * CONFIG_MAX_BYTES:
            raise ValueError("checkpoint is not a bounded regular file")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("id") != checkpoint_id:
            raise ValueError("checkpoint is malformed")
        return record

    def latest(self) -> dict[str, Any] | None:
        """Most recent change that has not been undone."""
        if not self.directory.is_dir():
            return None
        for path in sorted(self.directory.glob("ckpt_*.json"), reverse=True):
            try:
                record = self.load(path.stem)
            except (OSError, ValueError):
                continue
            if not record.get("undone"):
                return record
        return None

    def mark_undone(self, checkpoint_id: str) -> None:
        record = self.load(checkpoint_id)
        record["undone"] = True
        path = self.directory / f"{checkpoint_id}.json"
        temporary = self.directory / f".{checkpoint_id}.undo.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(record, ensure_ascii=False).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


class WorkspaceWriteOwner:
    """Change or restore one text file only after its exact diff is authorized and approved."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, checkpoints: CheckpointStore | None = None,
                 owner_id: str = "workspace_write", max_write_bytes: int | None = None):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.owner_id = owner_id
        self.max_write_bytes = (CONFIG_MAX_BYTES if owner_id == CONFIG_OWNER_ID
                                else MAX_WRITE_BYTES) if max_write_bytes is None else max_write_bytes
        if (type(self.max_write_bytes) is not int or not 1 <= self.max_write_bytes <= CONFIG_MAX_BYTES
                or (owner_id != CONFIG_OWNER_ID and self.max_write_bytes > MAX_WRITE_BYTES)):
            raise ValueError("workspace write size limit is invalid")
        self.gate = ProductActionGate(self.root, authority, owner_id=owner_id)
        self.checkpoints = checkpoints or CheckpointStore(self.root)

    # ── preview ────────────────────────────────────────────────

    def _target(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip() or len(path) > 4096 or "\0" in path:
            raise ValueError("path must be a bounded workspace-relative string")
        raw = Path(path).expanduser()
        lexical = Path(os.path.abspath(raw if raw.is_absolute() else self.root / raw))
        if self.root not in lexical.parents:
            raise ValueError("path must name a file inside the workspace")
        relative = lexical.relative_to(self.root)
        if (any(WorkspaceReadSystembility.is_sensitive_name(part) for part in relative.parts)
                and not (self.owner_id == CONFIG_OWNER_ID
                         and workspace_config_path_allowed(self.root, "workspace.config.write",
                                                           str(lexical)))):
            raise ValueError("sensitive paths cannot be written")
        if relative.name.casefold() in WRITE_PROTECTED_NAMES:
            raise ValueError("workspace identity markers cannot be written")
        return lexical

    def _missing_folders(self, target: Path) -> tuple[str, ...]:
        """Folders to create for target, in order; refuses symlinks and non-folders."""
        missing: list[str] = []
        current = self.root
        for part in target.parent.relative_to(self.root).parts:
            current = current / part
            if missing:
                missing.append(current.relative_to(self.root).as_posix())
                continue
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                missing.append(current.relative_to(self.root).as_posix())
                continue
            if stat.S_ISLNK(mode) or is_link(current):
                raise OSError("symlinked folders cannot be written through")
            if not stat.S_ISDIR(mode):
                raise ValueError("a parent of this path is not a folder")
        if len(missing) > MAX_NEW_FOLDERS:
            raise ValueError("too many new folders for one change")
        return tuple(missing)

    def _current(self, target: Path, missing: tuple[str, ...]) -> bytes | None:
        return None if missing else self._read_back(target)

    @staticmethod
    def _diff(before: bytes | None, after: bytes | None, relative: str) -> str:
        lines = []
        for line in difflib.unified_diff(
                ("" if before is None else before.decode("utf-8")).splitlines(keepends=True),
                ("" if after is None else after.decode("utf-8")).splitlines(keepends=True),
                fromfile="/dev/null" if before is None else f"a/{relative}",
                tofile="/dev/null" if after is None else f"b/{relative}", n=3):
            # A last line without a newline would otherwise be glued to the next one.
            lines.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        return "".join(lines)

    def preview(self, path: str, content: str, *, create_commands_folder: bool = False) -> WritePreview:
        """Compute the exact diff and request; performs reads only, never writes."""
        if not isinstance(content, str):
            raise ValueError("content must be text")
        encoded = content.encode("utf-8")
        target = self._target(path)
        relative = target.relative_to(self.root).as_posix()
        path_limit = self.max_write_bytes
        if self.owner_id == CONFIG_OWNER_ID:
            path_limit = (64 * 1024 if relative == ".isycode/config.json"
                          else 32 * 1024 if relative.startswith(".isycode/commands/")
                          else CONFIG_MAX_BYTES)
        if len(encoded) > path_limit:
            raise ValueError(f"content exceeds the {path_limit // 1024} KiB write limit")
        missing = self._missing_folders(target)
        if create_commands_folder:
            if (self.owner_id != CONFIG_OWNER_ID or relative != ".isycode/config.json"):
                raise ValueError("only config initialization can create its commands folder")
            for folder in self._missing_folders(self.root / ".isycode" / "commands" / "probe.md"):
                if folder not in missing:
                    missing = (*missing, folder)
        before = self._current(target, missing)
        if before == encoded:
            raise ValueError("the file already has exactly this content")
        diff = self._diff(before, encoded, relative)
        extra_folders = [folder for folder in missing
                         if folder not in {parent.as_posix() for parent in target.relative_to(self.root).parents}]
        if extra_folders:
            diff += "\nNew folders: " + ", ".join(extra_folders) + "\n"
        parameters = {
            "path": relative,
            "before_sha256": "absent" if before is None else _sha(before),
            "after_sha256": _sha(encoded),
            "size": len(encoded),
            "diff_sha256": _sha(diff.encode("utf-8")),
            "new_folders": list(missing),
        }
        if self.owner_id == CONFIG_OWNER_ID:
            request = ActionRequest("workspace.config.write", self.root, str(target),
                                    parameters, execution_owner="workspace_config")
        else:
            request = ActionRequest("workspace.files.write", self.root, str(target),
                                    parameters, execution_owner="workspace_write")
        return WritePreview(request, relative, diff, before is None, content)

    def preview_edit(self, path: str, old_text: str, new_text: str,
                     replace_all: bool = False) -> WritePreview:
        """Replace an exact fragment of an existing file; still a reviewed full write."""
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            raise ValueError("old_text must be non-empty text and new_text must be text")
        if old_text == new_text:
            raise ValueError("old_text and new_text are identical")
        target = self._target(path)
        current = self._current(target, self._missing_folders(target))
        if current is None:
            raise ValueError("the file does not exist; use workspace_write to create it")
        text = current.decode("utf-8")
        count = text.count(old_text)
        if count == 0:
            raise ValueError("old_text was not found in the file")
        if count > 1 and not replace_all:
            raise ValueError(f"old_text appears {count} times; add surrounding lines to make "
                             "it unique or set replace_all")
        return self.preview(path, text.replace(old_text, new_text))

    def preview_undo(self, checkpoint_id: str | None = None) -> WritePreview:
        """Restore the content from before one change; refuses if edited since."""
        record = (self.checkpoints.load(checkpoint_id) if checkpoint_id
                  else self.checkpoints.latest())
        if record is None:
            raise ValueError("there is no ISyCode change to undo")
        if record.get("undone"):
            raise ValueError("this change was already undone")
        if record.get("kind") == "move":
            return self._preview_move(record["to"], record["path"], undo_of=record["id"])
        target = self._target(record["path"])
        relative = target.relative_to(self.root).as_posix()
        current = self._current(target, self._missing_folders(target))
        if record.get("kind") == "delete":
            if current is not None:
                raise ValueError("a file with that name exists again; undo would overwrite it")
        elif current is None or _sha(current) != record["after_sha256"]:
            raise ValueError("the file changed after that ISyCode change; undo would discard "
                             "those edits")
        before = None if record["before"] is None else record["before"].encode("utf-8")
        diff = self._diff(current, before, relative)
        request = ActionRequest("workspace.files.restore", self.root, str(target), {
            "path": relative, "checkpoint_id": record["id"],
            "current_sha256": "absent" if current is None else _sha(current),
            "restore_sha256": "absent" if before is None else _sha(before),
            "diff_sha256": _sha(diff.encode("utf-8")),
        }, execution_owner="workspace_write")
        return WritePreview(request, relative, diff, False,
                            "" if before is None else record["before"], removes=before is None)

    def preview_delete(self, path: str) -> WritePreview:
        """Show the whole file being removed; only text files that /undo can restore."""
        target = self._target(path)
        relative = target.relative_to(self.root).as_posix()
        current = self._current(target, self._missing_folders(target))
        if current is None:
            raise ValueError("the file does not exist")
        diff = self._diff(current, None, relative)
        request = ActionRequest("workspace.files.delete", self.root, str(target), {
            "path": relative, "before_sha256": _sha(current),
            "diff_sha256": _sha(diff.encode("utf-8")),
        }, execution_owner="workspace_write")
        return WritePreview(request, relative, diff, False, current.decode("utf-8"), removes=True)

    def preview_move(self, path: str, to: str) -> WritePreview:
        return self._preview_move(path, to)

    def _preview_move(self, path: str, to: str, *, undo_of: str = "") -> WritePreview:
        source = self._target(path)
        destination = self._target(to)
        if source == destination:
            raise ValueError("the source and destination are the same")
        relative = source.relative_to(self.root).as_posix()
        target_relative = destination.relative_to(self.root).as_posix()
        self._missing_folders(source)
        digest = self._file_digest(source)
        if digest is None:
            raise ValueError("the file to move does not exist")
        missing = self._missing_folders(destination)
        if not missing and self._exists(destination):
            raise ValueError("the destination already exists; moves never overwrite")
        request = ActionRequest("workspace.files.move", self.root, str(source), {
            "path": relative, "to": target_relative, "sha256": digest,
            "new_folders": list(missing), "undo_of": undo_of,
        }, execution_owner="workspace_write")
        diff = f"rename from {relative}\nrename to {target_relative}\n"
        if missing:
            diff += "new folders: " + ", ".join(missing) + "\n"
        return WritePreview(request, relative, diff, False, "", destination=target_relative)

    # ── apply ──────────────────────────────────────────────────

    def _authorize(self, request: ActionRequest, approval: ActionApproval | None) -> str | None:
        try:
            authority, decision = self.gate.authorize(
                request, approvals=self.approvals, approval=approval)
        except Exception:
            return "authorization evaluation failed"
        if authority.allowed and decision.allowed:
            return None
        if not authority.allowed:
            return authority.reason[:300]
        return "; ".join(f"{item.name}: {item.reason}" for item in decision.checks
                         if not item.passed)[:300]

    def apply(self, preview: WritePreview, approval: ActionApproval | None) -> ActionOutcome:
        if not isinstance(preview, WritePreview):
            return ActionOutcome("File change denied.", "DENY", None, "preview has the wrong type")
        if preview.request.action_id == "workspace.files.restore":
            return self._apply_undo(preview, approval)
        if preview.request.action_id == "workspace.files.delete":
            return self._apply_delete(preview, approval)
        if preview.request.action_id == "workspace.files.move":
            return self._apply_move(preview, approval)
        try:
            create_commands_folder = (preview.request.execution_owner == CONFIG_OWNER_ID
                                      and ".isycode/commands"
                                      in preview.request.parameters.get("new_folders", ()))
            fresh = self.preview(preview.path, preview.content,
                                 create_commands_folder=create_commands_folder)
        except (OSError, ValueError) as exc:
            return ActionOutcome("File change denied.", "DENY", None,
                                 f"file cannot be re-checked: {str(exc)[:200]}")
        if fresh.request != preview.request:
            return ActionOutcome("File change denied.", "DENY", None,
                                 "the file changed since the reviewed diff; review a new one")
        denied = self._authorize(preview.request, approval)
        if denied is not None:
            return ActionOutcome("File change denied.", "DENY", None, denied)

        params = preview.request.parameters
        target = Path(preview.request.target)
        try:
            if ".isycode/commands" in params["new_folders"]:
                commands_directory = self.root / ".isycode" / "commands"
                if use_verified_fs():
                    VerifiedFS(self.root).ensure_folders(commands_directory,
                                                         tuple(params["new_folders"]))
                else:
                    directory_fd = self._open_directory(commands_directory,
                                                        tuple(params["new_folders"]))
                    os.close(directory_fd)
            before = self._replace(target, preview.content.encode("utf-8"),
                                   params["before_sha256"], tuple(params["new_folders"]))
            written = self._read_back(target)
            if written is None or _sha(written) != params["after_sha256"]:
                raise ValueError("written content does not match the approved digest")
        except (OSError, ValueError) as exc:
            receipt = self._receipt(preview.request, "FAILURE", "write_failed")
            return ActionOutcome("File change failed; the approved content is not verified.",
                                 "ERROR", receipt, str(exc)[:300])
        try:
            checkpoint = self.checkpoints.save({
                "time": time.time(), "path": params["path"],
                "before": None if before is None else before.decode("utf-8"),
                "after_sha256": params["after_sha256"],
                "new_folders": list(params["new_folders"]),
            })
        except (OSError, ValueError):
            checkpoint = ""
        result = json.dumps({"path": params["path"], "after_sha256": params["after_sha256"]},
                            sort_keys=True)
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), preview.request.action_id,
                                preview.request.digest, "ALLOW", "SUCCESS",
                                _sha(result.encode("utf-8")))
        if not self.gate.persist_receipt(preview.request, receipt):
            return ActionOutcome("File written, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        note = "reviewed diff applied and verified" + ("" if checkpoint else "; undo unavailable")
        return ActionOutcome(f"Wrote {params['path']}", "ALLOW", receipt, note)

    def _apply_undo(self, preview: WritePreview, approval: ActionApproval | None) -> ActionOutcome:
        params = preview.request.parameters
        try:
            fresh = self.preview_undo(params["checkpoint_id"])
        except (OSError, ValueError, KeyError) as exc:
            return ActionOutcome("Undo denied.", "DENY", None, str(exc)[:200])
        if fresh.request != preview.request:
            return ActionOutcome("Undo denied.", "DENY", None,
                                 "the file changed since the reviewed undo; review a new one")
        denied = self._authorize(preview.request, approval)
        if denied is not None:
            return ActionOutcome("Undo denied.", "DENY", None, denied)
        target = Path(preview.request.target)
        try:
            if preview.removes:
                self._remove(target, params["current_sha256"])
                if self._read_back(target) is not None:
                    raise ValueError("the file is still present")
            else:
                missing = self._missing_folders(target) if params["current_sha256"] == "absent" else ()
                self._replace(target, preview.content.encode("utf-8"),
                              params["current_sha256"], missing)
                written = self._read_back(target)
                if written is None or _sha(written) != params["restore_sha256"]:
                    raise ValueError("restored content does not match the checkpoint")
            self.checkpoints.mark_undone(params["checkpoint_id"])
        except (OSError, ValueError) as exc:
            return ActionOutcome("Undo failed; check the file.", "ERROR", None, str(exc)[:300])
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), preview.request.action_id,
                                preview.request.digest, "ALLOW", "SUCCESS",
                                _sha(f"restored:{params['checkpoint_id']}".encode()))
        if not self.gate.persist_receipt(preview.request, receipt):
            return ActionOutcome("Undo applied, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        return ActionOutcome(f"Undid the change to {params['path']}", "ALLOW", receipt,
                             "checkpoint restored and verified")

    def _finish(self, request: ActionRequest, event: str, text: str, note: str) -> ActionOutcome:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                                "ALLOW", "SUCCESS", _sha(event.encode("utf-8")))
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome(f"{text}, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt, note)

    def _apply_delete(self, preview: WritePreview, approval: ActionApproval | None) -> ActionOutcome:
        try:
            fresh = self.preview_delete(preview.path)
        except (OSError, ValueError) as exc:
            return ActionOutcome("Delete denied.", "DENY", None, f"file cannot be re-checked: {str(exc)[:200]}")
        if fresh.request != preview.request:
            return ActionOutcome("Delete denied.", "DENY", None,
                                 "the file changed since it was reviewed; review it again")
        denied = self._authorize(preview.request, approval)
        if denied is not None:
            return ActionOutcome("Delete denied.", "DENY", None, denied)
        params = preview.request.parameters
        target = Path(preview.request.target)
        try:
            self._remove(target, params["before_sha256"])
            if self._exists(target):
                raise ValueError("the file is still present")
        except (OSError, ValueError) as exc:
            return ActionOutcome("Delete failed; check the file.", "ERROR", None, str(exc)[:300])
        try:
            checkpoint = self.checkpoints.save({
                "kind": "delete", "time": time.time(), "path": params["path"],
                "before": preview.content, "after_sha256": "absent", "new_folders": []})
        except (OSError, ValueError):
            checkpoint = ""
        return self._finish(preview.request, f"deleted:{params['path']}", f"Deleted {params['path']}",
                            "reviewed delete applied" + ("" if checkpoint else "; undo unavailable"))

    def _apply_move(self, preview: WritePreview, approval: ActionApproval | None) -> ActionOutcome:
        params = preview.request.parameters
        try:
            fresh = self._preview_move(params["path"], params["to"], undo_of=params["undo_of"])
            if params["undo_of"]:
                record = self.checkpoints.load(params["undo_of"])
                if record.get("undone") or record.get("kind") != "move":
                    raise ValueError("that move was already undone")
        except (OSError, ValueError) as exc:
            return ActionOutcome("Move denied.", "DENY", None, f"file cannot be re-checked: {str(exc)[:200]}")
        if fresh.request != preview.request:
            return ActionOutcome("Move denied.", "DENY", None,
                                 "the file or destination changed since review; review it again")
        denied = self._authorize(preview.request, approval)
        if denied is not None:
            return ActionOutcome("Move denied.", "DENY", None, denied)
        source = Path(preview.request.target)
        destination = self.root / params["to"]
        try:
            self._move(source, destination, params["sha256"], tuple(params["new_folders"]))
            if self._file_digest(destination) != params["sha256"] or self._exists(source):
                raise ValueError("the moved file could not be verified")
        except (OSError, ValueError) as exc:
            return ActionOutcome("Move failed; check both paths.", "ERROR", None, str(exc)[:300])
        checkpoint = "undo"
        try:
            if params["undo_of"]:
                self.checkpoints.mark_undone(params["undo_of"])
            else:
                checkpoint = self.checkpoints.save({
                    "kind": "move", "time": time.time(), "path": params["path"],
                    "to": params["to"], "after_sha256": params["sha256"], "before": None,
                    "new_folders": list(params["new_folders"])})
        except (OSError, ValueError):
            checkpoint = ""
        verb = "Moved back" if params["undo_of"] else "Moved"
        return self._finish(preview.request, f"moved:{params['path']}:{params['to']}",
                            f"{verb} {params['path']} → {params['to']}",
                            "reviewed move applied" + ("" if checkpoint else "; undo unavailable"))

    def _receipt(self, request: ActionRequest, outcome: str, event: str) -> ActionReceipt | None:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", outcome,
                                _sha(f"{outcome}:{event}".encode()))
        return receipt if self.gate.persist_receipt(request, receipt) else None

    # ── descriptor-safe filesystem helpers ─────────────────────

    def _open_directory(self, directory: Path, create: tuple[str, ...] = ()) -> int:
        """Walk from the root with O_NOFOLLOW; create only the approved missing folders."""
        if use_verified_fs():
            raise OSError("descriptor walks are not available on this platform")
        relative = directory.relative_to(self.root)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root, flags)
        walked = Path()
        try:
            for part in relative.parts:
                walked = walked / part
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if walked.as_posix() not in create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                    child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _checked_text(self, data: bytes | None) -> bytes | None:
        if data is None:
            return None
        if len(data) > self.max_write_bytes:
            raise ValueError("existing file exceeds the workspace write size limit")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("existing file is not UTF-8 text") from exc
        return data

    def _verified_read(self, target: Path) -> bytes | None:
        try:
            return self._checked_text(VerifiedFS(self.root).read_file(target, self.max_write_bytes))
        except FileNotFoundError:
            return None

    def _read_at(self, parent_fd: int, name: str) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("only regular files can be written")
            if info.st_size > self.max_write_bytes:
                raise ValueError("existing file exceeds the workspace write size limit")
            data = os.read(descriptor, self.max_write_bytes + 1)
        finally:
            os.close(descriptor)
        if len(data) > self.max_write_bytes:
            raise ValueError("existing file exceeds the workspace write size limit")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("existing file is not UTF-8 text") from exc
        return data

    def _read_back(self, target: Path) -> bytes | None:
        if use_verified_fs():
            return self._verified_read(target)
        try:
            parent_fd = self._open_directory(target.parent)
        except FileNotFoundError:
            return None
        try:
            return self._read_at(parent_fd, target.name)
        finally:
            os.close(parent_fd)

    def _replace(self, target: Path, data: bytes, expected_before: str,
                 new_folders: tuple[str, ...]) -> bytes | None:
        """Atomically replace target; returns the content that was replaced."""
        if use_verified_fs():
            filesystem = VerifiedFS(self.root)
            filesystem.ensure_folders(target.parent, new_folders)
            current = self._verified_read(target)
            if ("absent" if current is None else _sha(current)) != expected_before:
                raise ValueError("the file changed during approval; nothing was written")
            filesystem.replace(target, data, current, lambda: self._verified_read(target))
            return current
        parent_fd = self._open_directory(target.parent, create=new_folders)
        temporary = f".{target.name}.isycode-{secrets.token_hex(6)}.tmp"
        created = False
        try:
            current = self._read_at(parent_fd, target.name)
            if ("absent" if current is None else _sha(current)) != expected_before:
                raise ValueError("the file changed during approval; nothing was written")
            mode = 0o644
            if current is not None:
                mode = stat.S_IMODE(os.stat(target.name, dir_fd=parent_fd,
                                            follow_symlinks=False).st_mode)
            flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
            descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            created = True
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(descriptor, view):]
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            created = False
            os.fsync(parent_fd)
            return current
        finally:
            if created:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(parent_fd)

    def _exists(self, target: Path) -> bool:
        try:
            os.lstat(target)
        except FileNotFoundError:
            return False
        return True

    def _file_digest(self, target: Path) -> str | None:
        """SHA-256 of any regular file up to 16 MiB, opened without following links."""
        if use_verified_fs():
            try:
                data = VerifiedFS(self.root).read_file(target, MAX_MOVE_BYTES)
            except FileNotFoundError:
                return None
            return None if data is None else _sha(data)
        try:
            parent_fd = self._open_directory(target.parent)
        except FileNotFoundError:
            return None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(target.name, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                return None
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError("only regular files can be moved")
                digest = hashlib.sha256()
                total = 0
                while chunk := os.read(descriptor, 1024 * 1024):
                    total += len(chunk)
                    if total > MAX_MOVE_BYTES:
                        raise ValueError("files over 16 MiB cannot be moved by ISyCode")
                    digest.update(chunk)
                return digest.hexdigest()
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def _move(self, source: Path, destination: Path, expected: str,
              new_folders: tuple[str, ...]) -> None:
        """Hard-link then unlink: never replaces an existing destination."""
        if self._file_digest(source) != expected:
            raise ValueError("the file changed during approval; nothing was moved")
        if use_verified_fs():
            VerifiedFS(self.root).move(source, destination, new_folders)
            return
        source_fd = self._open_directory(source.parent)
        try:
            destination_fd = self._open_directory(destination.parent, create=new_folders)
            try:
                os.link(source.name, destination.name, src_dir_fd=source_fd,
                        dst_dir_fd=destination_fd, follow_symlinks=False)
                os.unlink(source.name, dir_fd=source_fd)
                os.fsync(destination_fd)
                os.fsync(source_fd)
            finally:
                os.close(destination_fd)
        finally:
            os.close(source_fd)

    def _remove(self, target: Path, expected_current: str) -> None:
        """Remove a file ISyCode created, only if it is still exactly that content."""
        if use_verified_fs():
            current = self._verified_read(target)
            if current is None or _sha(current) != expected_current:
                raise ValueError("the file changed; nothing was removed")
            VerifiedFS(self.root).remove(target)
            return
        parent_fd = self._open_directory(target.parent)
        try:
            current = self._read_at(parent_fd, target.name)
            if current is None or _sha(current) != expected_current:
                raise ValueError("the file changed; nothing was removed")
            os.unlink(target.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


__all__ = ["CheckpointStore", "DELETE_TOOL", "DELETE_TOOL_NAME", "EDIT_TOOL", "EDIT_TOOL_NAME",
           "MOVE_TOOL", "MOVE_TOOL_NAME", "WRITE_TOOL", "WRITE_TOOL_NAME",
           "WorkspaceWriteOwner", "WritePreview"]
