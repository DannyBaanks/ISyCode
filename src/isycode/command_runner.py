"""Run one reviewed command inside the workspace sandbox after Authority and IsySentinel.

The argv is never given to a shell. Bubblewrap exposes read-only system files
and a private copy of the workspace; every sensitive path the chat tools refuse
(``.git``, ``.env``, keys…) is masked, the ``.isyroot`` marker is read-only,
and a seccomp bootstrap denies socket syscalls before the program starts.
The network namespace is not shared: a project command has no route to the host
network, and there is no separate grant that turns that route back on.
The user tree is unchanged until that measured diff is promoted. There is no
host-shell fallback. Each run needs a ``workspace.command.run`` grant for the
exact sandbox executable plus a fresh approval bound to the reviewed request.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from isycode.action_runtime import (
    COMMAND_DEFAULT_STAGE_BYTES, COMMAND_MAX_STAGE_BYTES,
    COMMAND_MAX_OUTPUT_BYTES, COMMAND_MAX_TIMEOUT_S, ActionOutcome,
    ActionReceipt, ProductActionGate, WorkspaceReadSystembility, command_argv_valid,
    command_relative_path_valid,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.staging import (
    StagingError, cleanup_staging, measure_changes, prepare_staging, promote_accounted,
)
from isycode.workspace_authority import WorkspaceAuthority
from isycode.platform_sandbox import sandbox_backend
from isycode.winfs import is_link

OWNER_ID = "workspace_command"
COMMAND_TOOL_NAME = "workspace_run"
DEFAULT_TIMEOUT_S = 120
# Compatibility exports for callers of the original Linux sandbox helpers.
PYTHON = "/usr/bin/python3"


def command_bootstrap(timeout_s: int) -> str:
    from isycode.platform_posix_sandbox import command_bootstrap as bootstrap
    return bootstrap(timeout_s)


COMMAND_TOOL = {"type": "function", "function": {
    "name": COMMAND_TOOL_NAME,
    "description": (
        "Run one program (for example tests, a build or a linter) in a sandbox of this workspace. "
        "The user reviews the exact command and must approve every run. There is no shell: pass "
        "the program and its arguments as a list, without pipes, redirects or variables. The "
        "network is blocked and sensitive files are hidden. Commands may change workspace files "
        "and those changes cannot be undone with /undo."),
    "parameters": {"type": "object", "properties": {
        "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                 "description": "Program and arguments, e.g. [\"python3\", \"-m\", \"pytest\", \"-q\"]."},
        "background": {"type": "boolean", "description": "TUI only: return a process ID immediately after review; inspect or stop it in Ctrl+S ShellBox. Existing timeout and sandbox still apply."},
        "cwd": {"type": "string", "description": "Workspace-relative folder; defaults to the root."},
        "scope": {"type": "string", "description": "Optional workspace-relative folder to stage in isolation for a small project inside a large workspace. Paths remain workspace-relative; siblings are not mounted."},
        "max_stage_bytes": {"type": "integer", "minimum": 1, "maximum": COMMAND_MAX_STAGE_BYTES,
                            "description": "Proposed temporary input-copy budget in bytes; default 536870912 (512 MiB). Above-default proposals always require the user's exact-command approval, even in trusted Classic. Not extra permissions; sandbox and effect limits remain unchanged. Expansion is not supported on Windows. Prefer a smaller scope when possible."},
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": COMMAND_MAX_TIMEOUT_S,
                      "description": f"Seconds before the command is stopped; default {DEFAULT_TIMEOUT_S}."},
    }, "required": ["argv"], "additionalProperties": False},
}}


FLOW_COMMAND_DESCRIPTION = (
    "Run a command in a sandbox of this workspace. Flow mode: commands run without asking the "
    "user. A shell is available inside the sandbox: for pipes, &&, redirects, globs or "
    "variables pass [\"bash\", \"-c\", \"...\"]; plain programs can still be passed as a list. "
    "Only this workspace is visible and writable; sensitive files are hidden and the network "
    "is blocked unless the user granted it for this session. Changes are measured before they "
    "reach the workspace and the user can undo the whole turn. Push, credentials and anything "
    "outside the workspace still need the user.")


def command_tool(mode: str | None) -> dict:
    """The command tool as the model sees it in this workspace mode.

    Only the wording changes: the sandbox, staging, limits and the grant are the
    same, and Flow decides nothing by itself (workspace_trust.quiet_request).
    """
    if mode != "flow":
        return COMMAND_TOOL
    function = {**COMMAND_TOOL["function"], "description": FLOW_COMMAND_DESCRIPTION}
    return {**COMMAND_TOOL, "function": function}


def _no_symlinks(root: Path, relative: str) -> bool:
    current = root
    for part in relative.split("/"):
        current = current / part
        try:
            if is_link(current):
                return False
        except OSError:
            return False
    return True


def sandbox_executable() -> str | None:
    return sandbox_backend.executable()


def resolve_program(root: Path, name: str) -> str:
    return sandbox_backend.resolve_program(root, name)


def sensitive_entries(root: Path, *, reject_hardlinks: bool = False) -> tuple[tuple[str, bool], ...]:
    """Every sensitive file or folder in the workspace, as (relative path, is_folder).

    Symlinks are not masked: only the workspace is mounted, so their targets
    are either outside the sandbox or a real entry that is masked itself. The
    scan is exhaustive: command execution never proceeds with only a partial
    list of sensitive paths, and large workspaces are not rejected by an
    arbitrary entry-count ceiling.
    """
    found: list[tuple[str, bool]] = []
    # A hardlink is the same file under a harmless name, so a name-only mask
    # misses it. Remember sensitive inodes and every multi-link file, then mask
    # the links that share an inode with a sensitive file.
    secret_inodes: set[tuple[int, int]] = set()
    linked: list[tuple[str, tuple[int, int]]] = []

    def inode(entry: os.DirEntry) -> tuple[tuple[int, int], int] | None:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        return (info.st_dev, info.st_ino), info.st_nlink

    def collect_secret_files(folder: str) -> None:
        with os.scandir(folder) as entries:
            for entry in entries:
                if is_link(Path(entry.path)):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    collect_secret_files(entry.path)
                elif entry.is_file(follow_symlinks=False) and (facts := inode(entry)):
                    secret_inodes.add(facts[0])

    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                if is_link(Path(entry.path)):
                    continue
                is_folder = entry.is_dir(follow_symlinks=False)
                if WorkspaceReadSystembility.is_sensitive_name(entry.name):
                    found.append((Path(entry.path).relative_to(root).as_posix(), is_folder))
                    if is_folder:
                        collect_secret_files(entry.path)
                    elif facts := inode(entry):
                        secret_inodes.add(facts[0])
                elif is_folder:
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and (facts := inode(entry)) and facts[1] > 1:
                    linked.append((Path(entry.path).relative_to(root).as_posix(), facts[0]))
    found.extend((relative, False) for relative, key in linked if reject_hardlinks or key in secret_inodes)
    return tuple(sorted(found))


def masked_digest(masks: tuple[tuple[str, bool], ...]) -> str:
    return hashlib.sha256(json.dumps(masks, separators=(",", ":")).encode("utf-8")).hexdigest()


def sandbox_command(sandbox: str, root: Path, program: str, argv: tuple[str, ...], cwd: str,
                    masks: tuple[tuple[str, bool], ...], *, timeout_s: int = DEFAULT_TIMEOUT_S) -> list[str]:
    """Compatibility entry point for the Linux argv builder."""
    from isycode.platform_posix_sandbox import sandbox_command as build
    return build(sandbox, root, program, argv, cwd, masks, timeout_s=timeout_s)


@dataclass(frozen=True)
class CommandPreview:
    request: ActionRequest
    argv: tuple[str, ...]
    program: str
    cwd: str
    timeout_s: int
    masks: tuple[tuple[str, bool], ...]
    scope: str = "."
    max_stage_bytes: int = COMMAND_DEFAULT_STAGE_BYTES


class CommandRunOwner:
    """The only execution owner for ``workspace.command.run``."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)

    def prepare(self, argv: object, cwd: object = ".",
                timeout_s: object = DEFAULT_TIMEOUT_S, *, scope: object = ".",
                max_stage_bytes: object = COMMAND_DEFAULT_STAGE_BYTES) -> CommandPreview:
        """Build the exact request the user reviews. Raises ValueError when it cannot run."""
        if isinstance(argv, list):
            argv = tuple(argv)
        if not command_argv_valid(argv):
            raise ValueError("argv must be 1–64 non-empty strings without NUL characters")
        cwd = "." if cwd in (None, "", "./") else cwd
        if isinstance(cwd, str):
            cwd = cwd.removeprefix("./").rstrip("/") or "."
        if not command_relative_path_valid(cwd, allow_root=True):
            raise ValueError("cwd must be a non-sensitive folder inside the workspace")
        if cwd != "." and (not _no_symlinks(self.root, cwd) or not (self.root / cwd).is_dir()):
            raise ValueError("cwd must be an existing folder without symlinks")
        if type(timeout_s) is not int or not 1 <= timeout_s <= COMMAND_MAX_TIMEOUT_S:
            raise ValueError(f"timeout must be 1–{COMMAND_MAX_TIMEOUT_S} seconds")
        if type(max_stage_bytes) is not int or not 1 <= max_stage_bytes <= COMMAND_MAX_STAGE_BYTES:
            raise ValueError(f"staging budget must be 1-{COMMAND_MAX_STAGE_BYTES} bytes (at most 8 GiB)")
        if os.name == "nt" and max_stage_bytes > COMMAND_DEFAULT_STAGE_BYTES:
            raise ValueError("Windows staging expansion is not supported; use a smaller scope")
        sandbox = sandbox_executable()
        if sandbox is None:
            raise ValueError(sandbox_backend.unavailable_reason())
        program = resolve_program(self.root, argv[0])
        if not isinstance(scope, str) or not command_relative_path_valid(scope, allow_root=True):
            raise ValueError("scope must be a non-sensitive workspace-relative folder")
        if scope != "." and (not _no_symlinks(self.root, scope) or not (self.root / scope).is_dir()):
            raise ValueError("scope must be an existing folder without symlinks")
        if scope != "." and cwd != "." and not (cwd == scope or cwd.startswith(scope + "/")):
            raise ValueError("cwd is outside the selected staging scope")
        masks = self._scope_masks(scope)
        from isycode.rtk_integration import plan as rtk_plan
        rtk = rtk_plan(argv, program)
        identity = sandbox_backend.identity()
        request = ActionRequest(
            "workspace.command.run", self.root, program,
            {"argv": argv, "program": program, "cwd": cwd, "timeout_s": timeout_s,
             "network": "denied", "executable": sandbox, "workspace_root": str(self.root),
             "masked_sha256": masked_digest(masks), "masked_count": len(masks),
             "max_output_bytes": COMMAND_MAX_OUTPUT_BYTES,
             **({"sandbox_identity": identity} if identity is not None else {}),
              **({"scope": scope} if scope != "." else {}),
              **({"max_stage_bytes": max_stage_bytes}
                 if max_stage_bytes != COMMAND_DEFAULT_STAGE_BYTES else {}),
             **({"rtk": rtk} if rtk else {})},
            execution_owner="workspace_command")
        return CommandPreview(request, argv, program, cwd, timeout_s, masks, scope, max_stage_bytes)

    def _scope_masks(self, scope: str) -> tuple[tuple[str, bool], ...]:
        entries = sensitive_entries(self.root / scope, reject_hardlinks=self.authority.mode() == "flow")
        return entries if scope == "." else tuple((scope + "/" + path, folder) for path, folder in entries)

    async def run(self, preview: CommandPreview,
                  approval: ActionApproval | None, *, on_output: Callable[[str], None] | None = None) -> ActionOutcome:
        """Run in staging and promote the measured diff after the process exits."""
        self._on_output = on_output
        try:
            return await self._run(preview, approval, promote=True)
        finally:
            self._on_output = None

    async def run_staged(self, preview: CommandPreview,
                         approval: ActionApproval | None) -> ActionOutcome:
        """Run in staging and leave the user tree untouched."""
        return await self._run(preview, approval, promote=False)

    async def _run(self, preview: CommandPreview, approval: ActionApproval | None, *,
                   promote: bool) -> ActionOutcome:
        request = preview.request
        # Re-derive the sandbox facts: a new secret or a swapped program after
        # review denies instead of running with a stale mask set.
        try:
            fresh = await asyncio.to_thread(self.prepare, list(preview.argv), preview.cwd,
                                            preview.timeout_s, scope=preview.scope,
                                            max_stage_bytes=preview.max_stage_bytes)
            if fresh != preview:
                raise ValueError("sensitive files, command scope or the program changed after review")
            masks = await asyncio.to_thread(self._scope_masks, preview.scope)
            program = await asyncio.to_thread(resolve_program, self.root, preview.argv[0])
        except (OSError, ValueError) as exc:
            return ActionOutcome("Command denied.", "DENY", None, str(exc)[:200] or "sandbox facts unavailable")
        if (masks != preview.masks or masked_digest(masks) != request.parameters["masked_sha256"]
                or program != preview.program or sandbox_executable() != request.parameters["executable"]):
            return ActionOutcome("Command denied.", "DENY", None,
                                 "sensitive files or the program changed after review")
        if request.parameters.get("rtk", {}).get("decision") == "ask" and approval is None:
            return ActionOutcome("Command denied.", "DENY", None, "RTK requested explicit review")
        if preview.max_stage_bytes > COMMAND_DEFAULT_STAGE_BYTES and (
                not isinstance(approval, ActionApproval) or approval.mode != "user"):
            return ActionOutcome("Command denied.", "DENY", None,
                                 "a larger staging budget requires explicit user approval for this command")
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("Command denied.", "DENY", None, reason)
        try:
            result = await self._execute(preview, promote=promote)
        except (OSError, RuntimeError, ValueError) as exc:
            detail = str(exc).strip() or type(exc).__name__
            return ActionOutcome("Command could not start.", "ERROR", None,
                                 f"sandboxed command failed to start ({detail[:200]})")
        if result.get('sandbox_cleanup', {}).get('state') == 'uncertain':
            return ActionOutcome(json.dumps(result, ensure_ascii=False, sort_keys=True),
                'NOT_VERIFIABLE', None,
                'command finished; file effects are recorded in the ledger, but sandbox cleanup is uncertain')
        if "rtk" in result:
            from isycode.rtk_integration import archive_result, record_stats
            try:
                await asyncio.to_thread(archive_result, result)
            except (OSError, ValueError):
                return ActionOutcome("Command evidence unavailable.", "NOT_VERIFIABLE", None,
                                     "RTK result artifact could not be persisted")
            record_stats(self.root, result)
        result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "workspace.command.run", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text):
            return ActionOutcome("Command receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Command receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        promotion = result.get("staging", {}).get("promotion") or {}
        if promotion.get("state") == "uncertain":
            note = "command finished; the effect ledger is uncertain and further changes are blocked"
        elif promotion.get("state") == "denied":
            note = "command finished; its changes were not promoted (" + str(promotion.get("reason", ""))[:160] + ")"
        else:
            note = f"sandboxed command finished with exit code {result['exit_code']}"
        return ActionOutcome(result_text, "ALLOW", receipt, note)

    async def _execute(self, preview: CommandPreview, *, promote: bool) -> dict:
        params = preview.request.parameters
        try:
            stage_task = asyncio.create_task(asyncio.to_thread(
                prepare_staging, self.root, scope=preview.scope,
                max_stage_bytes=params.get("max_stage_bytes")))
            try:
                staging = await asyncio.shield(stage_task)
            except asyncio.CancelledError:
                # A copying worker cannot be killed: finish it before cleanup so
                # cancellation never leaves an orphan or deletes an active copy.
                try:
                    abandoned = await stage_task
                except (OSError, RuntimeError, ValueError):
                    pass
                else:
                    await asyncio.to_thread(cleanup_staging, abandoned)
                raise
        except StagingError as exc:
            raise OSError(str(exc)) from exc
        original_staging = staging
        proc = None
        result = None
        try:
            proc = await sandbox_backend.start(staging.root, preview.program, preview.argv,
                preview.cwd, preview.masks, preview.timeout_s, executable=params['executable'],
                identity=params.get('sandbox_identity'))
            if hasattr(proc, 'staged_root'):
                staging = replace(staging, root=proc.staged_root)
            output = bytearray()
            total = 0
            timed_out = False

            async def drain() -> None:
                nonlocal total
                while chunk := await proc.stdout.read(8192):
                    total += len(chunk)
                    room = COMMAND_MAX_OUTPUT_BYTES - len(output)
                    if room > 0:
                        accepted = chunk[:room]
                        output.extend(accepted)
                        callback = getattr(self, "_on_output", None)
                        if callback is not None:
                            callback(accepted.decode("utf-8", errors="replace"))
                await proc.wait()

            try:
                await asyncio.wait_for(drain(), timeout=preview.timeout_s)
            except asyncio.TimeoutError:
                timed_out = True
                self._kill(proc)
                await proc.wait()
            except asyncio.CancelledError:
                self._kill(proc)
                await proc.wait()
                raise
            result = {"argv": list(preview.argv), "cwd": preview.cwd,
                      "exit_code": proc.returncode, "timed_out": timed_out,
                      "output": output.decode("utf-8", errors="replace"),
                      "output_truncated": total > len(output), "output_bytes": total}
            await sandbox_backend.finish(proc)
            if "rtk" in params:
                from isycode.rtk_integration import finish
                result["command_success"] = proc.returncode == 0 and not timed_out
                await finish(params["rtk"], result, bytes(output))
            changes = measure_changes(staging)
            if promote:
                from isycode.effect_ledger import EffectLedger, LedgerDenied
                revoked = self._revoked_effect(changes)
                try:
                    if revoked:
                        applied, refused, pending = [], [item["path"] for item in changes], []
                        promotion = {"state": "denied", "reason": revoked}
                    else:
                        applied, refused, promotion = promote_accounted(staging, changes)
                        pending = []
                except LedgerDenied as exc:
                    try:
                        recovered = EffectLedger(self.root).reconcile()
                    except LedgerDenied:
                        recovered = "UNCERTAIN"
                    applied, refused, pending = [], [], []
                    promotion = {"state": exc.effect_state if recovered != "UNCERTAIN" else "uncertain",
                                 "reason": str(exc)[:300]}
            else:
                applied, refused = [], []
                pending = [item["path"] for item in changes]
                promotion = {"state": "staged"}
            result["staging"] = {
                        "backend": "copy",
                        "promoted_count": len(applied),
                        "promoted": applied[:300],
                        "pending_count": len(pending),
                        "pending": pending[:300],
                        "refused_count": len(refused),
                        "refused": refused[:300],
                        "promotion": promotion,
                    }
            return result
        finally:
            try:
                if proc is not None:
                    await sandbox_backend.close(proc)
            except (OSError, RuntimeError) as exc:
                if result is None or 'staging' not in result:
                    raise
                result['sandbox_cleanup'] = {'state': 'uncertain', 'reason': str(exc)[:300]}
            finally:
                cleanup_staging(staging)
                if staging.root != original_staging.root:
                    cleanup_staging(original_staging)

    def _revoked_effect(self, changes: list[dict]) -> str | None:
        """Why the measured diff may not reach the user tree, or None.

        The command approval covers running the program; its file effects still
        answer to the file grants. An explicit denial (which Classic does not
        override) or a path outside a grant's prefixes refuses the whole diff.
        """
        grants = self.authority.effective_policy().get("grants", {})
        for change in changes:
            action = ("workspace.files.delete" if change.get("kind") == "delete"
                      else "workspace.files.write")
            grant = grants.get(action, {})
            if grant.get("enabled") is False:
                return f"{action} is revoked"
            prefixes = grant.get("path_prefixes") if grant.get("enabled") is True else None
            if prefixes:
                target = self.root / str(change.get("path", ""))
                if not any(target == Path(prefix) or Path(prefix) in target.parents
                           for prefix in prefixes):
                    return f"{change.get('path')} is outside the {action} grant"
        return None

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        sandbox_backend.terminate(proc)


__all__ = [
    "COMMAND_TOOL", "COMMAND_TOOL_NAME", "FLOW_COMMAND_DESCRIPTION", "command_tool", "CommandPreview", "CommandRunOwner", "DEFAULT_TIMEOUT_S",
    "masked_digest", "resolve_program", "sandbox_command", "sandbox_executable",
    "sensitive_entries",
]
