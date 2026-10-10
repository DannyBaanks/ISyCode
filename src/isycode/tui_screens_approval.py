"""Approval modals for writes, commands, commits, and deletes.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Button, Checkbox, Static
from isycode.command_runner import CommandPreview
from isycode.git_owner import CommitPreview
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from pathlib import Path
from rich.syntax import Syntax
from rich.text import Text
from isycode.workspace_write import WritePreview
import shlex



class ReviewConsentScreen(ModalScreen[bool]):
    """Show the exact user-provided text before sending it to a reviewer API."""

    CSS = """
ReviewConsentScreen { align: center middle; background: #000000 58%; }
    #review-consent { width: 90%; max-width: 100; height: 85%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #review-consent-title { height: 2; color: #9b5de5; text-style: bold; }
    #review-consent-warning { height: 3; color: #fbbf24; }
    #review-consent-artifact { height: 1fr; border: none; background: #242529; padding: 1; overflow-y: auto; }
    #review-consent-actions { height: 3; align-horizontal: right; }
    #review-consent-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel_review", "Cancel"),
                Binding("ctrl+c", "cancel_review", "Cancel", show=False)]

    def __init__(self, artifact: str) -> None:
        super().__init__()
        self.artifact = artifact

    def compose(self) -> ComposeResult:
        with Vertical(id="review-consent"):
            yield Static("External model review · GPT 6 Luna · OpenAI API", id="review-consent-title")
            yield Static("Only the text below will be sent. The reviewer has no tools. One HTTP request, max 1,200 output tokens; automatic retries are disabled.", id="review-consent-warning")
            with VerticalScroll(id="review-consent-artifact"):
                yield Static(Text(self.artifact))
            with Horizontal(id="review-consent-actions"):
                yield Button("Cancel", id="review-cancel")
                yield Button("Send this text", id="review-send", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "review-send")

    def action_cancel_review(self) -> None:
        self.dismiss(False)


class ApprovalScreen(ModalScreen[bool]):
    """Approve with y, reject with n or Esc; Reject stays the focused default.

    Plain (non-priority) bindings: a text field inside the screen still types y and n.
    """

    BINDINGS = [Binding("y", "approve", "Approve"), Binding("n", "decline", "Reject")]

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)


class ContextAccessScreen(ModalScreen[dict | None]):
    """Human Y/N gate for one context file, with optional exact-file memory."""

    CSS = """
    ContextAccessScreen { align: center middle; background: #000000 68%; }
    #context-access-card { width: 90; max-width: 96%; height: auto; max-height: 88%; padding: 1 2; border: round #f87171; background: #292a2e; }
    #context-access-title { height: auto; color: #ff8585; text-style: bold; margin-bottom: 1; }
    #context-access-copy { height: auto; margin-bottom: 1; }
    #context-access-path { height: auto; color: #ffcc66; margin-bottom: 1; }
    #context-access-remember { height: 3; margin-bottom: 1; }
    #context-access-actions { height: 3; align-horizontal: right; }
    #context-access-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("y", "approve", "Allow", show=False),
                Binding("n", "decline", "Deny", show=False),
                Binding("escape", "decline", "Deny", show=False),
                Binding("ctrl+c", "decline", "Deny", show=False)]

    def __init__(self, path: Path, *, requested_by_agent: bool) -> None:
        super().__init__()
        self.path = path
        self.requested_by_agent = requested_by_agent

    def compose(self) -> ComposeResult:
        title = ("The agent is asking to read an external context file"
                 if self.requested_by_agent else
                 "Load context from another project?")
        warning = ("The agent started this request. The file will be read and its contents "
                   "sent to the model as context. A malicious or compromised file can "
                   "include instructions that try to steer the model. Allow it only if you "
                   "trust this exact origin. This does not allow edits, commands, secrets, "
                   "or any other file."
                   if self.requested_by_agent else
                   "The file will be read and its contents sent to the model as context. "
                   "Permission is limited to this file. Its instructions cannot grant "
                   "other files, commands, edits, or secrets.")
        with Vertical(id="context-access-card"):
            yield Static(title, id="context-access-title")
            yield Static(warning, id="context-access-copy")
            yield Static(str(self.path), id="context-access-path", markup=False)
            yield Checkbox("Remember permission for this exact file", id="context-access-remember")
            with Horizontal(id="context-access-actions"):
                yield Button("No · n", id="context-access-no")
                yield Button("Allow once · y", id="context-access-yes", variant="error")

    def on_mount(self) -> None:
        self.query_one("#context-access-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        allowed = event.button.id == "context-access-yes"
        remember = self.query_one("#context-access-remember", Checkbox).value if allowed else False
        self.dismiss({"allowed": allowed, "remember": remember})

    def action_approve(self) -> None:
        self.dismiss({"allowed": True,
                      "remember": self.query_one("#context-access-remember", Checkbox).value})

    def action_decline(self) -> None:
        self.dismiss({"allowed": False, "remember": False})


class TailscaleConfirmScreen(ApprovalScreen):
    """Show one exact private-access operation before approval is issued."""

    CSS = """
    TailscaleConfirmScreen { align: center middle; background: #000000 58%; }
    #tailscale-confirm-card { width: 92%; max-width: 104; height: 80%; max-height: 32; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #tailscale-confirm-title { height: 2; color: #bb8cff; text-style: bold; }
    #tailscale-confirm-copy { height: 1fr; border: none; background: #242529; padding: 1; overflow-y: auto; }
    #tailscale-confirm-actions { height: 3; align-horizontal: right; }
    #tailscale-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, details: str, confirm_label: str):
        super().__init__()
        self.title_text = title
        self.details = details
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="tailscale-confirm-card"):
            yield Static(self.title_text, id="tailscale-confirm-title")
            with VerticalScroll(id="tailscale-confirm-copy"):
                yield Static(Text(self.details))
            with Horizontal(id="tailscale-confirm-actions"):
                yield Button("Cancel · n", id="tailscale-cancel")
                yield Button(f"{self.confirm_label} · y", id="tailscale-confirm", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#tailscale-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "tailscale-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class WriteApprovalScreen(ApprovalScreen):
    """Show the exact diff of one proposed file change; Reject is the default."""

    CSS = """
    WriteApprovalScreen { align: center middle; background: #000000 58%; }
    #write-approval-card { width: 110; max-width: 96%; height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #write-approval-title { height: 2; color: #bb8cff; text-style: bold; }
    #write-approval-summary { height: auto; margin-bottom: 1; }
    #write-approval-peer { height: auto; margin-bottom: 1; color: #e9c778; display: none; }
    #write-approval-diff { height: 1fr; border: none; background: #202126; }
    #write-approval-actions { height: 3; dock: bottom; align-horizontal: right; }
    #write-approval-actions Button { margin-left: 1; width: 1fr; min-width: 0; padding: 0 1; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, preview: WritePreview, *, replaces_whole_file: bool = False,
                 allow_automatic_edits: bool = True, allow_session_trust: bool = False) -> None:
        super().__init__()
        self.preview = preview
        self.replaces_whole_file = replaces_whole_file
        self.allow_automatic_edits = allow_automatic_edits
        self.allow_session_trust = allow_session_trust

    def compose(self) -> ComposeResult:
        lines = self.preview.diff.splitlines()
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        if self.preview.kind == "move":
            kind = ("Undo · move back" if self.preview.is_undo else "Move file")
        elif self.preview.kind == "delete":
            kind = "Delete file"
        elif self.preview.is_undo:
            kind = "Undo · remove file" if self.preview.removes else "Undo · restore file"
        elif self.preview.created:
            kind = "Create new file"
        else:
            kind = "Replace whole file" if self.replaces_whole_file else "Change file"
        with Vertical(id="write-approval-card"):
            yield Static(f"{kind} · {self.preview.path}", id="write-approval-title", markup=False)
            yield Static(
                f"Folder: {self.preview.request.workspace_root}\n" +
                (f"+{added} / -{removed} lines. This puts the file back as it was before ISyCode's "
                 "last change; nothing changes unless you apply it."
                 if self.preview.is_undo else
                 f"+{added} / -{removed} lines. The assistant proposed this change; nothing is written "
                 "unless you apply it. If the file changes before it is applied, the change is refused."),
                id="write-approval-summary", markup=False)
            yield Static("", id="write-approval-peer", markup=False)
            with VerticalScroll(id="write-approval-diff"):
                from isycode.diff_view import side_by_side_table
                yield Static(side_by_side_table(self.preview.diff, self.preview.path))
            with Horizontal(id="write-approval-actions"):
                yield Button("Reject · n", id="write-approval-reject")
                yield Button("Apply change · y", id="write-approval-apply", variant="warning")
                if self.allow_session_trust and self.preview.kind == "write" and not self.preview.is_undo:
                    yield Button("Trust folder this session · s", id="write-approval-session",
                                 variant="primary")
                if self.allow_automatic_edits and self.preview.kind == "write" and not self.preview.is_undo:
                    yield Button("Always allow…", id="write-approval-always", variant="error")

    async def on_mount(self) -> None:
        self.query_one("#write-approval-reject", Button).focus()
        # Advisory peer claims (grit) never gate this approval; a failure or a
        # missing registry only leaves the note hidden.
        loader = getattr(self.app, "_grit_peer_advisory", None)
        if loader is None:
            return
        try:
            note = await loader(self.preview.path)
        except Exception:
            return
        if note:
            widget = self.query_one("#write-approval-peer", Static)
            widget.update(note)
            widget.display = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "write-approval-always":
            self.dismiss("always")
        elif event.button.id == "write-approval-session":
            self.dismiss("session")
        else:
            self.dismiss(event.button.id == "write-approval-apply")

    def action_reject(self) -> None:
        self.dismiss(False)


class BatchApprovalScreen(ModalScreen[str]):
    """One gesture for N proposed writes; every write keeps its own one-use digest.

    Dismisses with "all" (apply every listed change), "each" (fall back to the
    per-file review flow) or "reject" (nothing is written).
    """

    CSS = """
    BatchApprovalScreen { align: center middle; background: #000000 58%; }
    #batch-approval-card { width: 110; max-width: 96%; height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #batch-approval-title { height: 2; color: #bb8cff; text-style: bold; }
    #batch-approval-summary { height: auto; margin-bottom: 1; }
    #batch-approval-diffs { height: 1fr; border: none; background: #202126; }
    #batch-approval-actions { height: 3; dock: bottom; align-horizontal: right; }
    #batch-approval-actions Button { margin-left: 1; width: 1fr; min-width: 0; padding: 0 1; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject all")]

    def __init__(self, previews: list[WritePreview]) -> None:
        super().__init__()
        self.previews = list(previews)

    def compose(self) -> ComposeResult:
        added = removed = 0
        for preview in self.previews:
            lines = preview.diff.splitlines()
            added += sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
            removed += sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        with Vertical(id="batch-approval-card"):
            yield Static(f"Review {len(self.previews)} proposed changes in one go",
                         id="batch-approval-title")
            yield Static(
                f"Total +{added} / -{removed} lines across {len(self.previews)} files. "
                "Approving here issues one single-use, digest-bound approval per change — "
                "no lasting permission is created, and a file that changes before it is "
                "applied is refused.", id="batch-approval-summary", markup=False)
            with VerticalScroll(id="batch-approval-diffs"):
                from isycode.diff_view import side_by_side_table
                for preview in self.previews:
                    yield Static(side_by_side_table(preview.diff, preview.path))
            with Horizontal(id="batch-approval-actions"):
                yield Button("Reject all · n", id="batch-approval-reject")
                yield Button("Review each · e", id="batch-approval-each")
                yield Button(f"Approve all {len(self.previews)} · a",
                             id="batch-approval-all", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#batch-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss({"batch-approval-all": "all",
                      "batch-approval-each": "each"}.get(event.button.id, "reject"))

    def action_reject(self) -> None:
        self.dismiss("reject")


class CommandApprovalScreen(ApprovalScreen):
    """Show the exact argv of one sandboxed command; Reject is the default."""

    CSS = """
    CommandApprovalScreen { align: center middle; background: #000000 58%; }
    #command-approval-card { width: 100; max-width: 96%; height: auto; max-height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #command-approval-title { height: 1; color: #bb8cff; text-style: bold; }
    #command-approval-argv { height: auto; max-height: 6; border: round #414650; background: #17191f; padding: 0 1; margin-bottom: 1; }
    #command-approval-actions { height: 5; align-horizontal: right; margin-top: 1; }
    #command-approval-actions Button { width: 1fr; height: 5; margin-left: 1; border: round #414650; background: #202126; }
    #command-approval-actions Button:focus { border: round #bb8cff; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, preview: CommandPreview) -> None:
        super().__init__()
        self.preview = preview

    def compose(self) -> ComposeResult:
        preview = self.preview
        hidden = len(preview.masks)
        with Vertical(id="command-approval-card"):
            yield Static(f"Run a command · {preview.cwd if preview.cwd != '.' else 'workspace root'}",
                         id="command-approval-title")
            with VerticalScroll(id="command-approval-argv"):
                yield Static(Text(shlex.join(preview.argv)))
                if "rtk" in preview.request.parameters:
                    rtk = preview.request.parameters["rtk"]
                    yield Static(Text("RTK suggestion: " + shlex.join(rtk["rewrite_argv"])))
                    yield Static(Text("Executes the original once; output compression by native RTK pipe.\n"
                                      + rtk["version"] + " · SHA-256 " + rtk["sha256"]))
            yield Static(
                f"Program: {preview.program}\n"
                f"Stops after {preview.timeout_s} s · network blocked · "
                f"{hidden} sensitive path{'s' if hidden != 1 else ''} hidden\n"
                "It may change files in this workspace; those changes cannot be undone with /undo. "
                "Nothing runs unless you approve it.")
            with Horizontal(id="command-approval-actions"):
                yield Button("Reject · n", id="command-approval-reject")
                yield Button("Run command · y", id="command-approval-run", variant="warning")

    def on_mount(self) -> None:
        card = self.query_one("#command-approval-card")
        card.border_title = "Command · review"
        self.query_one("#command-approval-argv").border_title = "Exact command"
        self.query_one("#command-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "command-approval-run")

    def action_reject(self) -> None:
        self.dismiss(False)


class CommitApprovalScreen(ApprovalScreen):
    """Show the exact message, files and diff of one proposed commit; Reject is the default."""

    CSS = """
    CommitApprovalScreen { align: center middle; background: #000000 58%; }
    #commit-approval-card { width: 110; max-width: 96%; height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #commit-approval-title { height: 2; color: #bb8cff; text-style: bold; }
    #commit-approval-summary { height: auto; max-height: 10; margin-bottom: 1; }
    #commit-approval-diff { height: 1fr; border: none; background: #202126; }
    #commit-approval-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #commit-approval-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, preview: CommitPreview) -> None:
        super().__init__()
        self.preview = preview

    def compose(self) -> ComposeResult:
        preview = self.preview
        files = ", ".join(preview.paths[:12]) + (f" and {len(preview.paths) - 12} more"
                                                  if len(preview.paths) > 12 else "")
        with Vertical(id="commit-approval-card"):
            yield Static(f"Commit {len(preview.paths)} file{'s' if len(preview.paths) != 1 else ''}",
                         id="commit-approval-title")
            yield Static(Text(f"{preview.message}\n\nFiles: {files}\nHooks do not run and "
                              "nothing is pushed. If a file changes before you approve, the "
                              "commit is refused."), id="commit-approval-summary")
            with VerticalScroll(id="commit-approval-diff"):
                yield Static(Syntax(preview.diff or "(no content changes)", "diff",
                                    theme="monokai", word_wrap=True))
            with Horizontal(id="commit-approval-actions"):
                yield Button("Reject · n", id="commit-approval-reject")
                yield Button("Commit · y", id="commit-approval-apply", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#commit-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "commit-approval-apply")

    def action_reject(self) -> None:
        self.dismiss(False)


class LocalMCPConfirmScreen(ApprovalScreen):
    """Show exactly what a local MCP server start or tool call will do; Cancel is the default."""

    CSS = """
    LocalMCPConfirmScreen { align: center middle; background: #000000 58%; }
    #local-mcp-card { width: 96; max-width: 96%; height: auto; max-height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #local-mcp-title { height: 2; color: #fbbf24; text-style: bold; }
    #local-mcp-payload { height: auto; max-height: 20; border: none; background: #242529; padding: 0 1; margin: 1 0; }
    #local-mcp-actions { height: 3; align-horizontal: right; }
    #local-mcp-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, body: str, payload: str, approve_label: str) -> None:
        super().__init__()
        self.title_text, self.body, self.payload, self.approve_label = title, body, payload, approve_label

    def compose(self) -> ComposeResult:
        with Vertical(id="local-mcp-card"):
            yield Static(self.title_text, id="local-mcp-title")
            yield Static(Text(self.body))
            with VerticalScroll(id="local-mcp-payload"):
                yield Static(Text(self.payload))
            with Horizontal(id="local-mcp-actions"):
                yield Button("Cancel · n", id="local-mcp-cancel")
                yield Button(f"{self.approve_label} · y", id="local-mcp-approve", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#local-mcp-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "local-mcp-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrowserReadPreviewScreen(ApprovalScreen):
    """Review the exact filtered page text before exposing it to the model."""

    CSS = """
    BrowserReadPreviewScreen { align: center middle; background: #000000 58%; }
    #browser-read-card { width: 100; max-width: 96%; height: 88%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #browser-read-title { height: 2; color: #fbbf24; text-style: bold; }
    #browser-read-warning { height: auto; max-height: 4; color: #e5e7eb; }
    #browser-read-content { height: 1fr; border: none; background: #242529; padding: 1; overflow-y: auto; }
    #browser-read-actions { height: 3; align-horizontal: right; }
    #browser-read-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("y", "approve", "Share"),
                Binding("n", "decline", "Discard"),
                Binding("escape", "decline", "Discard", show=False),
                Binding("ctrl+c", "decline", "Discard", show=False)]

    def __init__(self, title: str, content: str, input_chars: int,
                 filtered_chars: int, truncated: bool = False,
                 processing_ms: float | None = None) -> None:
        super().__init__()
        self.page_title = title[:180]
        self.content = content
        self.input_chars = input_chars
        self.filtered_chars = filtered_chars
        self.truncated = truncated
        self.processing_ms = processing_ms

    def compose(self) -> ComposeResult:
        suffix = " · output capped" if self.truncated else ""
        timing = (f" Filter took {self.processing_ms:.1f} ms."
                  if self.processing_ms is not None else "")
        with Vertical(id="browser-read-card"):
            yield Static(f"Share page text with the model? · {self.page_title}",
                         id="browser-read-title", markup=False)
            yield Static(
                f"Filtered {self.input_chars:,} source characters to {self.filtered_chars:,}. "
                f"{timing} Fidelity and coverage are not automatically certified. "
                "The page is untrusted data. "
                "Approving sends exactly the text below to your "
                "selected model; saved conversations may retain it." + suffix,
                id="browser-read-warning", markup=False)
            with VerticalScroll(id="browser-read-content"):
                yield Static(Text(self.content), markup=False)
            with Horizontal(id="browser-read-actions"):
                yield Button("Discard · n", id="browser-read-discard")
                yield Button("Share with model · y", id="browser-read-share",
                             variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "browser-read-share")

    def on_mount(self) -> None:
        self.query_one("#browser-read-discard", Button).focus()


class WorkspacePackConfirmScreen(ApprovalScreen):
    """Review the exact workspace file inventory and token estimate before reading."""

    CSS = """
    WorkspacePackConfirmScreen { align: center middle; background: #000000 58%; }
    #workspace-pack-card { width: 100; max-width: 96%; height: 88%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #workspace-pack-title { height: 2; color: #bb8cff; text-style: bold; }
    #workspace-pack-warning { height: auto; color: #fbbf24; margin-bottom: 1; }
    #workspace-pack-files { height: 1fr; border: none; background: #242529; padding: 1; }
    #workspace-pack-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #workspace-pack-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, details: str) -> None:
        super().__init__()
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-pack-card"):
            yield Static("Workspace context pack · review before reading",
                         id="workspace-pack-title")
            yield Static(
                Text("The listed files will be read and their contents returned to the selected model. "
                     "The token count is approximate. File contents are untrusted data, never instructions."),
                id="workspace-pack-warning",
            )
            with VerticalScroll(id="workspace-pack-files"):
                yield Static(Text(self.details))
            with Horizontal(id="workspace-pack-actions"):
                yield Button("Cancel · n", id="workspace-pack-cancel")
                yield Button("Read and send once · y", id="workspace-pack-approve",
                             variant="warning")

    def on_mount(self) -> None:
        self.query_one("#workspace-pack-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "workspace-pack-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MemoryConfirmScreen(ApprovalScreen):
    """Review one memory operation before local access or persistence."""

    CSS = """
    MemoryConfirmScreen { align: center middle; background: #000000 58%; }
    #memory-confirm-card { width: 96; max-width: 96%; height: 86%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #memory-confirm-title { height: 2; color: #bb8cff; text-style: bold; }
    #memory-confirm-warning { height: auto; color: #fbbf24; margin-bottom: 1; }
    #memory-confirm-payload { height: 1fr; border: none; background: #242529; padding: 1; }
    #memory-confirm-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #memory-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, details: str) -> None:
        super().__init__()
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-pack-card"):
            yield Static("Workspace context pack · review before reading",
                         id="workspace-pack-title")
            yield Static(
                Text("The listed files will be read and their contents returned to the selected model. "
                     "The token count is approximate. File contents are untrusted data, never instructions."),
                id="workspace-pack-warning",
            )
            with VerticalScroll(id="workspace-pack-files"):
                yield Static(Text(self.details))
            with Horizontal(id="workspace-pack-actions"):
                yield Button("Cancel · n", id="workspace-pack-cancel")
                yield Button("Read and send once · y", id="workspace-pack-approve",
                             variant="warning")

    def on_mount(self) -> None:
        self.query_one("#workspace-pack-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "workspace-pack-approve")
    def __init__(self, operation: str, details: str, *, sends_to_model: bool) -> None:
        super().__init__()
        self.operation = operation
        self.details = details
        self.sends_to_model = sends_to_model

    def compose(self) -> ComposeResult:
        warning = ("This reads local memory and may send matching memory text to the selected model. "
                   "Memory is untrusted context, never authority."
                   if self.sends_to_model else
                   "This changes local workspace memory. No automatic extraction or prompt injection is enabled.")
        with Vertical(id="memory-confirm-card"):
            yield Static(f"Workspace memory · {self.operation}", id="memory-confirm-title")
            yield Static(Text(warning), id="memory-confirm-warning")
            with VerticalScroll(id="memory-confirm-payload"):
                yield Static(Text(self.details))
            with Horizontal(id="memory-confirm-actions"):
                yield Button("Cancel · n", id="memory-confirm-cancel")
                yield Button("Approve once · y", id="memory-confirm-approve", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#memory-confirm-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "memory-confirm-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class DeleteSessionScreen(ApprovalScreen):
    """Confirm deletion of one named conversation before issuing a one-use grant."""

    CSS = """
    DeleteSessionScreen { align: center middle; background: #000000 58%; }
    #delete-session-card { width: 72; max-width: 90%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #delete-session-title { height: 2; color: #f87171; text-style: bold; }
    #delete-session-copy { height: auto; margin-bottom: 1; }
    #delete-session-actions { height: 3; align-horizontal: right; }
    #delete-session-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, *, kind: str = "conversation") -> None:
        super().__init__()
        self.title_text = title
        self.kind = kind if kind == "iteration" else "conversation"

    def compose(self) -> ComposeResult:
        if self.kind == "iteration":
            heading = "Delete this iteration?"
            button = "Delete iteration · y"
            detail = "This permanently removes this one iteration ledger."
        else:
            heading = "Delete this conversation?"
            button = "Delete conversation · y"
            detail = "This permanently removes this one transcript."
        with Vertical(id="delete-session-card"):
            yield Static(heading, id="delete-session-title")
            yield Static(f"{self.title_text}\n\n{detail} A one-use, session-bound approval will be checked before deletion.", id="delete-session-copy")
            with Horizontal(id="delete-session-actions"):
                yield Button("Keep · n", id="delete-session-cancel")
                yield Button(button, id="delete-session-confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#delete-session-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "delete-session-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
