"""Git, shell commands, file writes, and workspace read requests.

Moved verbatim from tui.py. TUIApp inherits this mixin.
"""
from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from isycode.workspace_authority import OneShotActionAuthority, WorkspaceAuthority, WorkspaceAuthorityError
from isycode.file_picker import ContextFilePickerOwner, FilePickerUnavailable
from isycode.action_runtime import LocalWorkspaceReadOwner, LPSSymbolOwner
from isycode.prompt_expansion import read_result_text
from isycode.git_owner import GitOwner, git_executable
from isycode.command_runner import CommandRunOwner, sandbox_executable
from isycode.workspace_write import DELETE_TOOL_NAME, MOVE_TOOL_NAME, WorkspaceWriteOwner
from isycode.authority_view import displayed_on
from isycode.security import ActionRequest
from textual.widgets import Button
from isycode.tui_theme import MUTED, GREEN, YELLOW, RED, CYAN
from isycode.tui_widgets import ChatArea, CommandOutputCard
from isycode.tui_composer import IdeaBox, ShellBox
from isycode.tui_screens_approval import ContextAccessScreen, WriteApprovalScreen, CommandApprovalScreen, CommitApprovalScreen
from isycode.tui_screens_sessions import ShellProcessesScreen


class WorkspaceMixin:
    def _open_context_menu(self) -> None:
        entries = [self._entry("Load workspace AGENTS.md", "context_project", "",
                               "Reads only this workspace's AGENTS.md through its read permission."),
                   self._entry("Choose context file (.md / .txt)", "context_inject", "",
                               "Choose a document here or in a sibling project; external files ask for explicit permission.")]
        if self._agent_context:
            entries.insert(0, self._entry(
                f"Injected · {self._agent_context['path']}", "context_info", "",
                f"ISyCode local receipt {self._agent_context['receipt_id'][:12]} verified PASS. Content stays in this process memory."))
            entries.append(self._entry("Remove injected context", "context_clear", ""))
        self._menu_stack = []
        self._render_menu("context_menu", "Context · workspace documents", entries)

    def _context_button_label(self) -> str:
        return f"Context: {Path(self._agent_context['path']).name}" if self._agent_context else "Context"

    async def _inject_agent_context(self) -> None:
        self._close_menu()
        try:
            picker = ContextFilePickerOwner(self._workspace_root)
            selected = await picker.choose()
        except FilePickerUnavailable as error:
            self._set_activity(f"Context picker unavailable · {error}", YELLOW)
            return
        if selected is None:
            self._set_activity("Context selection cancelled", MUTED)
            return
        source_root = picker.project_root_for(selected)
        if source_root == self._workspace_root.resolve(strict=True):
            relative = selected.relative_to(source_root).as_posix()
            await self._load_context_file(relative)
            return
        await self._confirm_and_load_external_context(
            selected, source_root, requested_by_agent=False)

    async def _confirm_and_load_external_context(
            self, selected: Path, source_root: Path, *, requested_by_agent: bool) -> str | None:
        """Ask Y/N before one exact external context read; optionally remember that file."""
        try:
            selected = ContextFilePickerOwner(self._workspace_root).validate(selected)
            if ContextFilePickerOwner(self._workspace_root).project_root_for(selected) != source_root:
                raise ValueError("the selected project folder changed")
        except (FilePickerUnavailable, OSError, ValueError) as exc:
            self._append(f"  Context request denied · {str(exc)[:180]}", YELLOW)
            return None
        consent = await self._await_screen(ContextAccessScreen(
            selected, requested_by_agent=requested_by_agent))
        if not consent or not consent.get("allowed"):
            self._append("  Context access declined · no file was read", MUTED)
            return None
        relative = selected.relative_to(source_root).as_posix()
        arguments = {"path": relative}
        target = str(source_root / relative)
        request = ActionRequest("workspace.context.inject", source_root, target,
                                arguments, execution_owner="workspace_read")
        try:
            authority = WorkspaceAuthority(source_root)
            if consent.get("remember"):
                # Persist only the exact selected document, never the sibling tree.
                authority.set_grant("workspace.context.inject", enabled=True,
                                    path_prefixes=[selected])
            else:
                authority = OneShotActionAuthority(authority, request)
            owner = LocalWorkspaceReadOwner(source_root, authority)
            outcome = await asyncio.to_thread(
                owner.execute, "workspace.context.inject", arguments)
        except (OSError, RuntimeError, ValueError, WorkspaceAuthorityError) as exc:
            self._append(f"  Context access failed · {type(exc).__name__}", YELLOW)
            return None
        text = read_result_text(outcome.text) if outcome.decision == "ALLOW" else ""
        if not text or outcome.receipt is None:
            self._append(f"  Context not loaded · {outcome.reason[:180]}", YELLOW)
            return None
        source = str(selected)
        self._agent_context = {"path": source, "text": text,
                               "receipt_id": outcome.receipt.receipt_id,
                               "verification": "PASS"}
        persistence = ("permission remembered for this file" if consent.get("remember")
                       else "one-time permission")
        requester = "agent request" if requested_by_agent else "user selection"
        self._append(f"  Context loaded · {source} · {requester} · {persistence} · "
                     f"receipt {outcome.receipt.receipt_id}", GREEN)
        self.query_one("#context-button", Button).label = self._context_button_label()
        return text

    async def _post_edit_diagnostics(self, path: str, text: str) -> list[dict] | None:
        """Pyright problems for a just-applied .py change, or None when checks are off."""
        server = next((item for item in self._lsp_inventory
                       if item.get("id") == "pyright" and item.get("state") == "sandbox_ready"), None)
        if server is None or not path.endswith(".py"):
            return None
        try:
            grant = WorkspaceAuthority(self._workspace_root).effective_policy().get(
                "grants", {}).get("lsp.diagnostics", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return None
        if not displayed_on("lsp.diagnostics", grant,
                            server["sandbox_executable"] in grant.get("executables", [])):
            return None
        owner = LPSSymbolOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                               self._action_approvals)
        outcome = await owner.diagnostics("pyright", path, text, self._lsp_inventory)
        if outcome.decision != "ALLOW":
            self._append(f"  Pyright check skipped · {outcome.reason[:160]}", MUTED)
            return None
        problems = [item for item in json.loads(outcome.text)["diagnostics"]
                    if item["severity"] in {"error", "warning"}]
        if not problems:
            self._append(f"  Pyright · {path} · no errors or warnings", GREEN)
        for item in problems[:15]:
            self._append(f"  Pyright {item['severity']} · {path}:{item['line']}:{item['column']} · "
                         f"{item['message'][:200]}", YELLOW if item["severity"] == "warning" else RED)
        return problems

    def _workspace_chat_tools_enabled(self, root: Path | None = None) -> bool:
        """Require explicit root-scoped grants for every read-only chat tool."""
        try:
            grants = WorkspaceAuthority(root or self._workspace_root).effective_policy().get("grants", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        root = str(root or self._workspace_root)
        return all(
            displayed_on(action_id, grants.get(action_id, {}),
                         root in grants.get(action_id, {}).get("path_prefixes", []))
            for action_id in (
                "workspace.files.list", "workspace.files.read", "workspace.files.search",
            )
        )

    def _workspace_read_owner(self) -> LocalWorkspaceReadOwner:
        root = self._folder_store().resolve(self._file_browser_alias)
        return LocalWorkspaceReadOwner(root, WorkspaceAuthority(root))

    def _workspace_request(self, action_id: str, path: str, **extra: str) -> ActionRequest:
        arguments = {"path": path, **extra}
        owner = self._workspace_read_owner()
        target = owner._lexical_target(path)
        return ActionRequest(action_id, owner.root, str(target), arguments,
                             execution_owner="workspace_read")

    async def _undo_last_change(self) -> None:
        """User-only: show the undo diff for the most recent ISyCode change and apply on approval."""
        owner = WorkspaceWriteOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                    self._action_approvals)
        try:
            preview = await asyncio.to_thread(owner.preview_undo)
        except (OSError, ValueError) as exc:
            self._append(f"  Nothing undone · {str(exc)[:200]}", YELLOW)
            return
        if not await self._await_screen(WriteApprovalScreen(preview)):
            self._append(f"  Undo cancelled · {preview.path} unchanged", MUTED)
            return
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        if outcome.decision == "ALLOW":
            self._append(f"  {outcome.text} · receipt {outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  Undo {outcome.decision} · {outcome.reason[:180]}", YELLOW)

    def _workspace_write_tool_enabled(self, root: Path | None = None) -> bool:
        """The write tool needs read tools plus a root-scoped write grant."""
        root = root or self._workspace_root
        if not self._workspace_chat_tools_enabled(root):
            return False
        try:
            grant = WorkspaceAuthority(root).effective_policy().get(
                "grants", {}).get("workspace.files.write", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        return displayed_on("workspace.files.write", grant,
                            str(root) in grant.get("path_prefixes", []))

    def _git_enabled(self, commit: bool = False) -> bool:
        if git_executable() is None or not self._workspace_chat_tools_enabled():
            return False
        try:
            grants = WorkspaceAuthority(self._workspace_root).effective_policy().get("grants", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        actions = ("git.commit",) if commit else ("git.status", "git.diff")
        return all(displayed_on(action, grants.get(action, {})) for action in actions)

    async def _git_tool(self, name: str, arguments: dict) -> str:
        """git_status / git_diff read through GitOwner; git_commit shows the diff first."""
        repository = arguments.get("repository")
        if repository is not None and not isinstance(repository, str):
            return json.dumps({"error": "repository must be a direct child folder name"})
        owner = GitOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                         self._action_approvals, repository=repository)
        if name == "git_status":
            outcome = await asyncio.to_thread(owner.status)
        elif name == "git_diff":
            path, staged = arguments.get("path", "."), arguments.get("staged", False)
            if not isinstance(path, str) or not isinstance(staged, bool):
                return json.dumps({"error": "path must be a string and staged a boolean"})
            outcome = await asyncio.to_thread(owner.diff, path, staged)
        else:
            message, paths = arguments.get("message"), arguments.get("paths")
            try:
                preview = await asyncio.to_thread(owner.preview_commit, message, paths)
            except (OSError, ValueError) as exc:
                reason = str(exc)[:200] or type(exc).__name__
                self._append(f"  Commit not proposed · {reason}", YELLOW)
                return json.dumps({"error": "commit cannot be proposed", "reason": reason})
            self._append(f"  Commit requested · {len(preview.paths)} files · review it", CYAN)
            if not await self._await_screen(CommitApprovalScreen(preview)):
                self._append("  Commit rejected · nothing was committed", MUTED)
                return json.dumps({"status": "rejected_by_user"})
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            outcome = await asyncio.to_thread(owner.commit, preview, approval)
        action = {"git_status": "git.status", "git_diff": "git.diff"}.get(name, "git.commit")
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append(f"  Git {outcome.decision} · {action} · {outcome.reason[:180]}", YELLOW)
            return json.dumps({"error": "ISyCode denied the git action", "reason": outcome.reason[:300]})
        if action == "git.status":
            result = json.loads(outcome.text)
            changes = result["changes"]
            self._append(f"  Git · {result['branch']} · "
                         + (f"{len(changes)} changed file{'s' if len(changes) != 1 else ''}"
                            if changes else "clean"), GREEN)
            for entry in changes[:40]:
                self._append(f"    {entry['status']} {entry['path']}", MUTED)
        elif action == "git.commit":
            commit_id = json.loads(outcome.text)["commit"][:12]
            self._append(f"  Committed {commit_id} · receipt {outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  Git ALLOW · {action} · receipt {outcome.receipt.receipt_id}", GREEN)
        return outcome.text

    def _command_tool_enabled(self) -> bool:
        """Commands need the read tools plus a grant for the current sandbox executable."""
        sandbox = sandbox_executable()
        if sandbox is None or not self._workspace_chat_tools_enabled():
            return False
        try:
            grant = WorkspaceAuthority(self._workspace_root).effective_policy().get(
                "grants", {}).get("workspace.command.run", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        return displayed_on("workspace.command.run", grant, sandbox in grant.get("executables", []))

    def action_toggle_shell_box(self):
        self._shell_mode = not self._shell_mode
        self.query_one("#idea-box", IdeaBox).display = not self._shell_mode
        self.query_one("#shell-box", ShellBox).display = self._shell_mode
        self._paint_shell_box()

    def _paint_shell_box(self):
        active = sum(job["status"] in {"queued", "running", "stopping"} for job in self._shell_jobs.values())
        self.query_one("#shell-box", ShellBox).update(f"ShellBox · {active} active · {len(self._shell_jobs)} total\nEnter / Space: processes · Ctrl+S: IdeaBox")

    def _open_shell_box(self):
        self.push_screen(ShellProcessesScreen())

    async def _run_workspace_command(self, arguments: dict) -> str:
        """Show one exact command, run it in the sandbox only if approved, return its result."""
        if not self._command_tool_enabled():
            if sandbox_executable() is None:
                reason = ("the sandbox backend is absent, so commands stay off. "
                          "There is no unsandboxed fallback.")
            else:
                reason = "commands are off here"
            self._append(f"  Command denied · workspace.command.run · {reason}", YELLOW)
            return json.dumps({"error": "sandboxed commands are not enabled for this workspace",
                               "reason": reason})
        background = arguments.get("background", False)
        if type(background) is not bool:
            return json.dumps({"error": "background must be a boolean"})
        if background and len(self._shell_jobs) >= 64:
            return json.dumps({"error": "session process history limit reached; start a new session"})
        owner = CommandRunOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                self._action_approvals)
        try:
            preview = await asyncio.to_thread(
                owner.prepare, arguments.get("argv"), arguments.get("cwd", "."),
                arguments.get("timeout_s", 120), scope=arguments.get("scope", "."))
        except (OSError, ValueError) as exc:
            reason = str(exc)[:200] or type(exc).__name__
            self._append(f"  Command denied · {reason}", YELLOW)
            return json.dumps({"error": "command cannot run", "reason": reason})
        shown = shlex.join(preview.argv)
        quiet = self._request_is_quiet(preview.request)
        if quiet:
            self._append(f"  Command · quiet Classic · {shown[:160]}", CYAN)
            approval = None
        else:
            self._append(f"  Command requested · {shown[:160]} · review it", CYAN)
            if not await self._await_screen(CommandApprovalScreen(preview)):
                self._append("  Command rejected · nothing ran", MUTED)
                return json.dumps({"status": "rejected_by_user", "argv": list(preview.argv)})
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        self._dismiss_idle()
        chat = self.query_one(ChatArea)
        card = CommandOutputCard(shown)
        chat.mount(card)
        chat.follow_tail()
        def show_output(chunk):
            card.append_output(chunk)
            chat.follow_tail()
        if background:
            job_id = "process-" + str(len(self._shell_jobs) + 1)
            job = {"command": shown, "status": "queued", "output": "", "task": None}
            async def execute_job():
                try:
                    async with self._command_run_lock:
                        job["status"] = "running"
                        self._paint_shell_box()
                        def output(chunk):
                            job["output"] = (job["output"] + chunk)[-262144:]
                            card.append_output(chunk)
                        outcome = await owner.run(preview, approval, on_output=output)
                    job["status"] = outcome.decision
                    job["output"] = outcome.text if outcome.decision == "ALLOW" else outcome.reason
                    if outcome.decision == "ALLOW":
                        result = json.loads(outcome.text)
                        job["status"] = "timeout" if result["timed_out"] else "exit " + str(result["exit_code"])
                        job["output"] = result["output"]
                    card.finish(job["status"], output=job["output"], receipt=outcome.receipt.receipt_id if outcome.receipt else "")
                except asyncio.CancelledError:
                    job["status"] = "cancelled"
                    card.finish("Cancelled")
                except Exception as exc:
                    job["status"] = "failed"
                    job["output"] = type(exc).__name__
                    card.finish("Failed")
                finally:
                    self._paint_shell_box()
            job["task"] = asyncio.create_task(execute_job())
            self._shell_jobs[job_id] = job
            self._paint_shell_box()
            return json.dumps({"process_id": job_id, "status": "queued", "background": True,
                               "inspect": "Ctrl+S → ShellBox → Enter", "timeout_s": preview.timeout_s})
        try:
            async with self._command_run_lock:
                outcome = await owner.run(preview, approval, on_output=show_output)
        except asyncio.CancelledError:
            card.finish("Cancelled")
            raise
        except Exception:
            card.finish("Failed")
            raise
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            card.finish(outcome.decision, output=outcome.reason[:300])
            return json.dumps({"error": "command did not run", "decision": outcome.decision,
                               "reason": outcome.reason[:300]})
        result = json.loads(outcome.text)
        status = ("stopped after the time limit" if result["timed_out"]
                  else f"exit code {result['exit_code']}")
        card.finish(status, output=result["output"], receipt=outcome.receipt.receipt_id,
                    truncated=result.get("output_truncated", False))
        chat.follow_tail()
        return outcome.text

    def _file_action_enabled(self, action: str) -> bool:
        try:
            grant = WorkspaceAuthority(self._workspace_root).effective_policy().get(
                "grants", {}).get(action, {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            return False
        return displayed_on(action, grant, str(self._workspace_root) in grant.get("path_prefixes", []))

    async def _dispatch_file_change(self, name: str, arguments: dict) -> str:
        """Delete or move one file after the user approves exactly that change."""
        action = "workspace.files.delete" if name == DELETE_TOOL_NAME else "workspace.files.move"
        if not self._workspace_write_tool_enabled() or not self._file_action_enabled(action):
            self._append(f"  Tool denied · {action} · not enabled for this workspace", YELLOW)
            return json.dumps({"error": f"{action} is not enabled for this workspace",
                               "how_to_enable": "Settings → Authority → Turn on all coding tools…"})
        path, destination = arguments.get("path"), arguments.get("to")
        if not isinstance(path, str) or (name == MOVE_TOOL_NAME and not isinstance(destination, str)):
            return json.dumps({"error": "path (and to, for a move) must be strings"})
        owner = WorkspaceWriteOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                    self._action_approvals)
        try:
            if name == DELETE_TOOL_NAME:
                preview = await asyncio.to_thread(owner.preview_delete, path)
            else:
                preview = await asyncio.to_thread(owner.preview_move, path, destination)
        except (OSError, ValueError) as exc:
            reason = str(exc)[:200] or type(exc).__name__
            self._append(f"  Tool denied · {action} · {reason}", YELLOW)
            return json.dumps({"error": "change cannot be previewed", "reason": reason})
        quiet = self._request_is_quiet(preview.request)
        if quiet:
            self._append(f"  Tool · quiet Classic · {action} · {preview.path}", CYAN)
            approval = None
        else:
            self._append(f"  Tool requested · {action} · {preview.path} · review it", CYAN)
            if not await self._await_screen(WriteApprovalScreen(preview)):
                self._append(f"  ✗ You rejected · {preview.path} · nothing changed", MUTED)
                return json.dumps({"status": "rejected_by_user", "approved_by_user": False,
                                   "path": preview.path})
            self._append(f"  ✓ You approved · {action.rsplit('.', 1)[-1]} {preview.path}", MUTED)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        if outcome.decision == "ALLOW" and outcome.receipt is not None:
            self._append(f"  Tool ALLOW · {outcome.text} · receipt {outcome.receipt.receipt_id}", GREEN)
            return json.dumps({"status": "done", "approved_by_user": not quiet,
                               "approval_mode": "quiet-profile" if quiet else "reviewed",
                               "result": outcome.text, "receipt": outcome.receipt.receipt_id})
        self._append(f"  Tool {outcome.decision} · {action} · {outcome.reason[:180]}", YELLOW)
        return json.dumps({"error": "change was not applied", "decision": outcome.decision,
                           "reason": outcome.reason[:300]})

    def _session_trust_active(self, folder_alias: str) -> bool:
        """In-memory, per-run trust. Classic-only, re-checked live: switching a
        workspace to Security suspends it without persisting anything."""
        if folder_alias not in self._session_auto_edits:
            return False
        try:
            return self._folder_store().auto_edit_available(folder_alias)
        except (OSError, ValueError):
            return False

    async def _dispatch_write_tool(self, arguments: dict, *, edit: bool = False,
                                   root: Path | None = None, folder_alias: str = 'main',
                                   batch_digest: str | None = None) -> str:
        """Preview a proposed change, show its diff, and apply only if the user approves."""
        path = arguments.get("path")
        root = root or self._workspace_root
        try:
            binding = self._folder_store().binding(folder_alias)
        except (OSError, ValueError) as exc:
            return json.dumps({"error": str(exc)[:180]})
        if not self._workspace_write_tool_enabled(root):
            self._append("  Tool denied · workspace.files.write · file editing is off", YELLOW)
            return json.dumps({"error": "file editing is not enabled for this workspace"})
        if edit:
            old_text, new_text = arguments.get("old_text"), arguments.get("new_text")
            replace_all = arguments.get("replace_all", False)
            if (not isinstance(path, str) or not isinstance(old_text, str)
                    or not isinstance(new_text, str) or not isinstance(replace_all, bool)):
                self._append("  Tool denied · workspace_edit · invalid arguments", YELLOW)
                return json.dumps({"error": "path, old_text and new_text must be strings"})
        else:
            content = arguments.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                self._append("  Tool denied · workspace.files.write · invalid arguments", YELLOW)
                return json.dumps({"error": "path and content must be strings"})
        owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root),
                                    self._action_approvals)
        try:
            if edit:
                preview = await asyncio.to_thread(owner.preview_edit, path, old_text, new_text,
                                                  replace_all)
            else:
                preview = await asyncio.to_thread(owner.preview, path, content)
        except (OSError, ValueError) as exc:
            reason = str(exc)[:200] or type(exc).__name__
            self._append(f"  Tool denied · workspace.files.write · {reason}", YELLOW)
            return json.dumps({"error": "change cannot be previewed", "reason": reason})
        replaces = not edit and not preview.created
        quiet = self._request_is_quiet(preview.request)
        # A batch gesture applies only to the exact previewed digest; any drift
        # since the batch screen falls back to an individual review.
        batch_approved = batch_digest is not None and batch_digest == preview.request.digest
        session_trusted = self._session_trust_active(folder_alias)
        if quiet:
            self._append(f"  Tool · quiet Classic · {'replace whole file' if replaces else 'edit'} · "
                         f"{preview.path}", CYAN)
            delegated = False
            choice = True
        elif batch_approved:
            self._append(f"  Tool · batch-approved · {'replace whole file' if replaces else 'edit'} · "
                         f"{preview.path}", CYAN)
            delegated = False
            choice = True
        elif session_trusted:
            self._append(f"  Tool · session trust · {'replace whole file' if replaces else 'edit'} · "
                         f"{preview.path}", CYAN)
            delegated = False
            choice = True
        else:
            self._append(f"  Tool requested · {'replace whole file' if replaces else 'edit'} · "
                         f"{preview.path} · review the diff", CYAN)
            try:
                delegated = self._folder_store().auto_edit_allowed(folder_alias)
            except (OSError, ValueError) as exc:
                return json.dumps({'error': f'Folder approval settings unavailable: {str(exc)[:120]}'})
            choice = True if delegated else await self._await_screen(
                WriteApprovalScreen(preview, replaces_whole_file=replaces,
                    allow_automatic_edits=self._folder_store().auto_edit_available(folder_alias),
                    allow_session_trust=self._folder_store().auto_edit_available(folder_alias)))
        if choice == 'always':
            delegated = await self._set_folder_auto_edit(folder_alias, True)
            choice = delegated
        if choice == 'session':
            self._session_auto_edits.add(folder_alias)
            session_trusted = True
            self._append(f"  Trust granted for this session only · folder {folder_alias} · "
                         "writes apply without asking until ISyCode closes; nothing is saved", MUTED)
            choice = True
        if not choice:
            self._append(f"  ✗ You rejected · {preview.path} · nothing was written", MUTED)
            return json.dumps({"status": "rejected_by_user", "approved_by_user": False,
                               "path": preview.path})
        try:
            current = self._folder_store().resolve(folder_alias, write=True)
            if (current != root or self._folder_store().binding(folder_alias) != binding
                    or not self._workspace_write_tool_enabled(root)):
                raise ValueError('Folder or write access changed during review')
            if delegated and not self._folder_store().auto_edit_allowed(folder_alias):
                raise ValueError('Automatic edit approval was revoked')
            if session_trusted and not self._session_trust_active(folder_alias):
                raise ValueError('Session trust was suspended by a mode change')
        except (OSError, ValueError) as exc:
            return json.dumps({'error': str(exc)[:180]})
        if quiet:
            self._append(f"  ✓ Quiet Classic · {folder_alias} · {preview.path}", MUTED)
            approval = None
        else:
            label = ('Batch-approved' if batch_approved else
                     'Session trust' if session_trusted else
                     'User-enabled automatic edits' if delegated else 'You approved')
            self._append(f"  ✓ {label} · {folder_alias} · {preview.path}", MUTED)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        if outcome.decision == "ALLOW" and outcome.receipt is not None:
            self._append(f"  Tool ALLOW · workspace.files.write · {preview.path} · "
                         f"receipt {outcome.receipt.receipt_id}", GREEN)
            if quiet:
                approval_mode, approved_by_user = "quiet-profile", False
            elif batch_approved:
                approval_mode, approved_by_user = "batch", True
            elif session_trusted:
                approval_mode, approved_by_user = "session-trust", True
            elif delegated:
                approval_mode, approved_by_user = "delegated", False
            else:
                approval_mode, approved_by_user = "reviewed", True
            result = {"status": "written", "approved_by_user": approved_by_user,
                      "approval_mode": approval_mode, "folder": folder_alias, "path": preview.path,
                      "replaced_whole_file": replaces, "receipt": outcome.receipt.receipt_id}
            problems = await self._post_edit_diagnostics(preview.path, preview.content) if root == self._workspace_root else None
            if problems is not None:
                result["diagnostics"] = problems[:50]
            return json.dumps(result)
        self._append(f"  Tool {outcome.decision} · workspace.files.write · "
                     f"{outcome.reason[:180]}", YELLOW)
        return json.dumps({"error": "change was not written", "decision": outcome.decision,
                           "reason": outcome.reason[:300]})

    def _menu_folders_open(self, entry: dict[str, str | bool]) -> None:
        self._open_workspace_folders_menu()
        return

    def _menu_folder_add(self, entry: dict[str, str | bool]) -> None:
        self._close_menu()
        self.run_worker(self._add_workspace_folder(), group='folders')
        return

    def _menu_folder_browse(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._browse_workspace_folder(value), group='files')
        return

    def _menu_folder_remove(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        try:
            self._folder_store().remove(value)
            if self._file_browser_alias == value:
                self._file_browser_alias = 'main'
                self.run_worker(self._load_directory(str(self._workspace_root)), group='files')
        except (OSError, ValueError) as exc:
            self._append(f"  Folder not removed · {str(exc)[:160]}", YELLOW)
        self._open_workspace_folders_menu()
        return

    def _menu_folder_auto_on(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._set_folder_auto_edit(value, kind == 'folder_auto_on'), group='folders')
        return

    def _menu_workspace_config_init(self, entry: dict[str, str | bool]) -> None:
        self._close_menu()
        self.run_worker(self._initialize_workspace_config(), exclusive=True,
                        group="workspace-config")
        return

    def _menu_workspace_config_preferences(self, entry: dict[str, str | bool]) -> None:
        self._open_workspace_config_menu()
        return

    def _menu_workspace_config_migrate(self, entry: dict[str, str | bool]) -> None:
        self.run_worker(self._open_workspace_migration_menu(), exclusive=True,
                        group="workspace-config")
        return

    def _menu_workspace_config_migrate_item(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self.run_worker(self._copy_workspace_command(value), exclusive=True,
                        group="workspace-config")
        return

    def _menu_workspace_pref_role(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self.run_worker(self._change_workspace_preference(kind), exclusive=True,
                        group="workspace-config")
        return

    def _menu_context_inject(self, entry: dict[str, str | bool]) -> None:
        self.run_worker(self._inject_agent_context(), exclusive=True, group="context-inject")
        return

    def _menu_context_project(self, entry: dict[str, str | bool]) -> None:
        self._close_menu()
        self.run_worker(self._load_project_context(), exclusive=True, group="context-inject")
        return

    def _menu_context_clear(self, entry: dict[str, str | bool]) -> None:
        self._agent_context = None
        self.query_one("#context-button", Button).label = "Context"
        self._set_activity("Injected AGENTS.md context removed", MUTED)
        self._open_context_menu()
        return

    def _menu_context_info(self, entry: dict[str, str | bool]) -> None:
        self._open_context_menu()
        return

    def _menu_context_menu(self, entry: dict[str, str | bool]) -> None:
        self._open_context_menu()
        return
