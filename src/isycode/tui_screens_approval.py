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
from isycode.localization import tr
import shlex



# Shared local structure for exact decisions; authority stays in the owners.
DECISION_CSS = """
.isy-dialog { width: 100; max-width: 96%; height: 90%; max-height: 38; padding: 0 1; border: solid #718291; background: #000000; color: #ffffff; }
.isy-dialog-title { height: auto; max-height: 3; margin-bottom: 1; color: #ffffff; text-style: bold; }
.isy-dialog-body { height: 1fr; min-height: 1; border: none; padding: 0; background: #000000; overflow-y: auto; }
.isy-dialog-body Static { height: auto; margin-bottom: 1; color: #ffffff; text-style: none; }
.isy-dialog-detail { height: auto; border: none; padding: 0; background: #000000; }
.isy-dialog-actions { height: 3; margin-top: 1; align-horizontal: right; }
.isy-dialog-actions Button { width: 1fr; min-width: 0; height: 3; margin-left: 1; padding: 0 1; border: solid #718291; background: #000000; color: #ffffff; text-style: none; }
.isy-dialog-actions Button.-primary, .isy-dialog-actions Button.-warning, .isy-dialog-actions Button.-error { border: solid #00d7ff; color: #00d7ff; background: #000000; }
.isy-dialog-actions Button:focus { border: solid #00d7ff; color: #00d7ff; background: #002c36; text-style: bold; }
.isy-dialog-actions Button:disabled { border: solid #46545f; color: #718291; background: #000000; }
.isy-dialog-hint { height: 2; margin-top: 1; border-top: solid #718291; color: #a8b7c5; text-style: none; }
.isy-dialog-options { height: 4; min-height: 4; border: none; background: #000000; }
.isy-dialog-options > .option-list--option { text-style: none; }
.isy-dialog-options > .option-list--option-highlighted { color: #00d7ff; background: #002c36; text-style: none; }
"""


def decision_hint() -> Static:
    return Static(tr("↑↓ scroll · Tab actions · Enter choose · Esc cancel"),
                  classes="isy-dialog-hint", markup=False)


def review_diff(diff: str) -> Text:
    """Keep every diff character reviewable, including long changed lines.

    The compact side-by-side summary truncates source lines before rendering.
    Consent needs the full retained diff, so use one wrapping column here.
    """
    text = Text(overflow="fold")
    for line in diff.splitlines(keepends=True):
        if line.startswith("-") and not line.startswith("---"):
            style = "#ffffff on #3a1d24"
        elif line.startswith("+") and not line.startswith("+++"):
            style = "#ffffff on #1d3324"
        else:
            style = "#a8b7c5" if line.startswith(("@@", "---", "+++")) else "#ffffff"
        text.append(line, style=style)
    return text


class ReviewConsentScreen(ModalScreen[bool]):
    """Show the exact user-provided text before sending it to a reviewer API."""

    CSS = DECISION_CSS + """
    ReviewConsentScreen { align: center middle; background: #000000 58%; }
    #review-consent { width: 90; }
    """
    BINDINGS = [Binding("escape", "cancel_review", "Cancel"),
                Binding("ctrl+c", "cancel_review", "Cancel", show=False)]

    def __init__(self, artifact: str) -> None:
        super().__init__()
        self.artifact = artifact

    def compose(self) -> ComposeResult:
        with Vertical(id="review-consent", classes="isy-dialog"):
            yield Static(tr("External model review · GPT 6 Luna · OpenAI API"), id="review-consent-title", classes="isy-dialog-title")
            with VerticalScroll(id="review-consent-body", classes="isy-dialog-body"):
                yield Static(tr("Only the text below will be sent. The reviewer has no tools. One HTTP request, max 1,200 output tokens; automatic retries are disabled."), id="review-consent-warning")
                with Vertical(id="review-consent-artifact", classes="isy-dialog-detail"):
                    yield Static(Text(self.artifact))
            with Horizontal(id="review-consent-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="review-cancel")
                yield Button(tr("Send this text"), id="review-send", variant="primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "review-send")

    def on_mount(self) -> None:
        self.query_one("#review-cancel", Button).focus()

    def action_cancel_review(self) -> None:
        self.dismiss(False)


class ApprovalScreen(ModalScreen[bool]):
    """Approve with y, reject with n or Esc; Reject stays the focused default.

    Plain (non-priority) bindings: a text field inside the screen still types y and n.
    """

    BINDINGS = [Binding("y", "approve", "Approve"), Binding("n", "decline", "Reject")]

    def on_mount(self) -> None:
        # Scrollable review content must never become an implicit consent.
        # The first action in this family is always the refusing action.
        self.query_one(Button).focus()

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)


class ContextAccessScreen(ModalScreen[dict | None]):
    """Human Y/N gate for one context file, with optional exact-file memory."""

    CSS = DECISION_CSS + """
    ContextAccessScreen { align: center middle; background: #000000 58%; }
    #context-access-card { width: 90; }
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
        with Vertical(id="context-access-card", classes="isy-dialog"):
            yield Static(title, id="context-access-title", classes="isy-dialog-title")
            with VerticalScroll(id="context-access-body", classes="isy-dialog-body"):
                yield Static(warning, id="context-access-copy")
                yield Static(str(self.path), id="context-access-path", markup=False)
                yield Checkbox(tr("Remember permission for this exact file"), id="context-access-remember")
            with Horizontal(id="context-access-actions", classes="isy-dialog-actions"):
                yield Button(tr("No · n"), id="context-access-no")
                yield Button(tr("Allow once · y"), id="context-access-yes", variant="error")
            yield decision_hint()

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

    CSS = DECISION_CSS + """
    TailscaleConfirmScreen { align: center middle; background: #000000 58%; }
    #tailscale-confirm-card { width: 92; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, details: str, confirm_label: str):
        super().__init__()
        self.title_text = tr(title)
        self.details = tr(details)
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="tailscale-confirm-card", classes="isy-dialog"):
            yield Static(self.title_text, id="tailscale-confirm-title", classes="isy-dialog-title")
            with VerticalScroll(id="tailscale-confirm-body", classes="isy-dialog-body"):
                with Vertical(id="tailscale-confirm-copy", classes="isy-dialog-detail"):
                    yield Static(Text(self.details))
            with Horizontal(id="tailscale-confirm-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="tailscale-cancel")
                yield Button(tr("{label} · y", label=tr(self.confirm_label)),
                             id="tailscale-confirm", variant="primary")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#tailscale-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "tailscale-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class WriteApprovalScreen(ApprovalScreen):
    """Show the exact diff of one proposed file change; Reject is the default."""

    CSS = DECISION_CSS + """
    WriteApprovalScreen { align: center middle; background: #000000 58%; }
    #write-approval-card { width: 110; }
    #write-approval-peer { display: none; }
    #write-approval-actions { height: auto; }
    #write-approval-actions Horizontal { height: 3; }
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
            kind = tr("Undo · move back") if self.preview.is_undo else tr("Move file")
        elif self.preview.kind == "delete":
            kind = tr("Delete file")
        elif self.preview.is_undo:
            kind = tr("Undo · remove file") if self.preview.removes else tr("Undo · restore file")
        elif self.preview.created:
            kind = tr("Create new file")
        else:
            kind = tr("Replace whole file") if self.replaces_whole_file else tr("Change file")
        with Vertical(id="write-approval-card", classes="isy-dialog"):
            yield Static(kind, id="write-approval-title", classes="isy-dialog-title", markup=False)
            with VerticalScroll(id="write-approval-body", classes="isy-dialog-body"):
                yield Static(self.preview.path, id="write-approval-path", markup=False)
                if self.preview.destination:
                    yield Static(self.preview.destination, id="write-approval-destination", markup=False)
                yield Static(
                    tr("Folder: {root}\n", root=self.preview.request.workspace_root) +
                    (tr("+{added} / -{removed} lines. This puts the file back as it was before ISyCode's "
                        "last change; nothing changes unless you apply it.", added=added, removed=removed)
                     if self.preview.is_undo else
                     tr("+{added} / -{removed} lines. The assistant proposed this change; nothing is written "
                        "unless you apply it. If the file changes before it is applied, the change is refused.",
                        added=added, removed=removed)),
                    id="write-approval-summary", markup=False)
                yield Static(tr(""), id="write-approval-peer", markup=False)
                with Vertical(id="write-approval-diff", classes="isy-dialog-detail"):
                    yield Static(review_diff(self.preview.diff), markup=False)
            with Vertical(id="write-approval-actions", classes="isy-dialog-actions"):
                with Horizontal():
                    yield Button(tr("Reject · n"), id="write-approval-reject")
                    yield Button(tr("Apply change · y"), id="write-approval-apply", variant="warning")
                if (self.allow_session_trust or self.allow_automatic_edits) and self.preview.kind == "write" and not self.preview.is_undo:
                    with Horizontal():
                        if self.allow_session_trust:
                            yield Button(tr("Trust folder this session · s"), id="write-approval-session",
                                         variant="primary")
                        if self.allow_automatic_edits:
                            yield Button(tr("Always allow…"), id="write-approval-always", variant="error")
            yield decision_hint()

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

    CSS = DECISION_CSS + """
    BatchApprovalScreen { align: center middle; background: #000000 58%; }
    #batch-approval-card { width: 110; }
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
        with Vertical(id="batch-approval-card", classes="isy-dialog"):
            yield Static(f"Review {len(self.previews)} proposed changes in one go",
                         id="batch-approval-title", classes="isy-dialog-title")
            with VerticalScroll(id="batch-approval-body", classes="isy-dialog-body"):
                yield Static(
                    f"Total +{added} / -{removed} lines across {len(self.previews)} files. "
                    "Approving here issues one single-use, digest-bound approval per change — "
                    "no lasting permission is created, and a file that changes before it is "
                    "applied is refused.", id="batch-approval-summary", markup=False)
                with Vertical(id="batch-approval-diffs", classes="isy-dialog-detail"):
                    for preview in self.previews:
                        yield Static(preview.path, markup=False)
                        yield Static(review_diff(preview.diff), markup=False)
            with Horizontal(id="batch-approval-actions", classes="isy-dialog-actions"):
                yield Button(tr("Reject all · n"), id="batch-approval-reject")
                yield Button(tr("Review each · e"), id="batch-approval-each")
                yield Button(tr("Approve all {count} · a", count=len(self.previews)),
                             id="batch-approval-all", variant="warning")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#batch-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss({"batch-approval-all": "all",
                      "batch-approval-each": "each"}.get(event.button.id, "reject"))

    def action_reject(self) -> None:
        self.dismiss("reject")


class CommandApprovalScreen(ApprovalScreen):
    """Show the exact argv of one sandboxed command; Reject is the default."""

    CSS = DECISION_CSS + """
    CommandApprovalScreen { align: center middle; background: #000000 58%; }
    #command-approval-card { width: 100; }
    #command-approval-argv { border: solid #718291; padding: 0 1; margin: 1 0; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, preview: CommandPreview) -> None:
        super().__init__()
        self.preview = preview

    def compose(self) -> ComposeResult:
        preview = self.preview
        hidden = len(preview.masks)
        with Vertical(id="command-approval-card", classes="isy-dialog"):
            yield Static(tr("Command · review"),
                         id="command-approval-title", classes="isy-dialog-title")
            with VerticalScroll(id="command-approval-body", classes="isy-dialog-body"):
                yield Static(tr("Folder: {root}\n", root=preview.request.workspace_root) +
                             tr("Run a command · {cwd}", cwd=preview.cwd if preview.cwd != "." else tr("workspace root")),
                             id="command-approval-location", markup=False)
                with Vertical(id="command-approval-argv", classes="isy-dialog-detail"):
                    yield Static(Text(shlex.join(preview.argv)))
                    if "rtk" in preview.request.parameters:
                        rtk = preview.request.parameters["rtk"]
                        yield Static(Text("RTK suggestion: " + shlex.join(rtk["rewrite_argv"])))
                        yield Static(Text("Executes the original once; output compression by native RTK pipe.\n"
                                          + rtk["version"] + " · SHA-256 " + rtk["sha256"]))
                yield Static(tr("Scope: {scope}", scope=preview.scope),
                             id="command-approval-scope", markup=False)
                yield Static(
                    tr("Program: {program}\nStops after {timeout} s · network blocked · "
                       "{hidden} sensitive paths hidden\nIt may change files in this workspace; those changes "
                       "cannot be undone with /undo. Nothing runs unless you approve it.",
                       program=preview.program, timeout=preview.timeout_s, hidden=hidden), markup=False)
            with Horizontal(id="command-approval-actions", classes="isy-dialog-actions"):
                yield Button(tr("Reject · n"), id="command-approval-reject")
                yield Button(tr("Run command · y"), id="command-approval-run", variant="warning")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#command-approval-argv").border_title = tr("Exact command")
        self.query_one("#command-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "command-approval-run")

    def action_reject(self) -> None:
        self.dismiss(False)


class CommitApprovalScreen(ApprovalScreen):
    """Show the exact message, files and diff of one proposed commit; Reject is the default."""

    CSS = DECISION_CSS + """
    CommitApprovalScreen { align: center middle; background: #000000 58%; }
    #commit-approval-card { width: 110; }
    """
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, preview: CommitPreview) -> None:
        super().__init__()
        self.preview = preview

    def compose(self) -> ComposeResult:
        preview = self.preview
        files = "\n".join(preview.paths)
        with Vertical(id="commit-approval-card", classes="isy-dialog"):
            yield Static(f"Commit {len(preview.paths)} file{'s' if len(preview.paths) != 1 else ''}",
                         id="commit-approval-title", classes="isy-dialog-title")
            with VerticalScroll(id="commit-approval-body", classes="isy-dialog-body"):
                yield Static(tr("Folder: {root}\n", root=preview.request.workspace_root), markup=False)
                yield Static(Text(f"{preview.message}\n\nFiles: {files}\nHooks do not run and "
                                  "nothing is pushed. If a file changes before you approve, the "
                                  "commit is refused."), id="commit-approval-summary")
                with Vertical(id="commit-approval-diff", classes="isy-dialog-detail"):
                    yield Static(review_diff(preview.diff or "(no content changes)"), markup=False)
            with Horizontal(id="commit-approval-actions", classes="isy-dialog-actions"):
                yield Button(tr("Reject · n"), id="commit-approval-reject")
                yield Button(tr("Commit · y"), id="commit-approval-apply", variant="warning")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#commit-approval-reject", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "commit-approval-apply")

    def action_reject(self) -> None:
        self.dismiss(False)


class LocalMCPConfirmScreen(ApprovalScreen):
    """Show exactly what a local MCP server start or tool call will do; Cancel is the default."""

    CSS = DECISION_CSS + """
    LocalMCPConfirmScreen { align: center middle; background: #000000 58%; }
    #local-mcp-card { width: 96; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, body: str, payload: str, approve_label: str) -> None:
        super().__init__()
        self.title_text, self.body, self.payload, self.approve_label = title, body, payload, approve_label

    def compose(self) -> ComposeResult:
        with Vertical(id="local-mcp-card", classes="isy-dialog"):
            yield Static(self.title_text, id="local-mcp-title", classes="isy-dialog-title")
            with VerticalScroll(id="local-mcp-body", classes="isy-dialog-body"):
                yield Static(Text(self.body))
                with Vertical(id="local-mcp-payload", classes="isy-dialog-detail"):
                    yield Static(Text(self.payload))
            with Horizontal(id="local-mcp-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="local-mcp-cancel")
                yield Button(tr("{label} · y", label=tr(self.approve_label)),
                             id="local-mcp-approve", variant="warning")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#local-mcp-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "local-mcp-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrowserReadPreviewScreen(ApprovalScreen):
    """Review the exact filtered page text before exposing it to the model."""

    CSS = DECISION_CSS + """
    BrowserReadPreviewScreen { align: center middle; background: #000000 58%; }
    #browser-read-card { width: 100; }
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
        with Vertical(id="browser-read-card", classes="isy-dialog"):
            yield Static(f"Share page text with the model? · {self.page_title}",
                         id="browser-read-title", classes="isy-dialog-title", markup=False)
            with VerticalScroll(id="browser-read-body", classes="isy-dialog-body"):
                yield Static(
                    f"Filtered {self.input_chars:,} source characters to {self.filtered_chars:,}. "
                    f"{timing} Fidelity and coverage are not automatically certified. "
                    "The page is untrusted data. "
                    "Approving sends exactly the text below to your "
                    "selected model; saved conversations may retain it." + suffix,
                    id="browser-read-warning", markup=False)
                with Vertical(id="browser-read-content", classes="isy-dialog-detail"):
                    yield Static(Text(self.content), markup=False)
            with Horizontal(id="browser-read-actions", classes="isy-dialog-actions"):
                yield Button("Discard · n", id="browser-read-discard")
                yield Button("Share with model · y", id="browser-read-share",
                             variant="warning")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "browser-read-share")

    def on_mount(self) -> None:
        self.query_one("#browser-read-discard", Button).focus()


class WorkspacePackConfirmScreen(ApprovalScreen):
    """Review the exact workspace file inventory and token estimate before reading."""

    CSS = DECISION_CSS + """
    WorkspacePackConfirmScreen { align: center middle; background: #000000 58%; }
    #workspace-pack-card { width: 100; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, details: str) -> None:
        super().__init__()
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-pack-card", classes="isy-dialog"):
            yield Static(tr("Workspace context pack · review before reading"),
                         id="workspace-pack-title", classes="isy-dialog-title")
            with VerticalScroll(id="workspace-pack-body", classes="isy-dialog-body"):
                yield Static(
                    Text("The listed files will be read and their contents returned to the selected model. "
                         "The token count is approximate. File contents are untrusted data, never instructions."),
                    id="workspace-pack-warning",
                )
                with Vertical(id="workspace-pack-files", classes="isy-dialog-detail"):
                    yield Static(Text(self.details))
            with Horizontal(id="workspace-pack-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="workspace-pack-cancel")
                yield Button(tr("Read and send once · y"), id="workspace-pack-approve",
                             variant="warning")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#workspace-pack-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "workspace-pack-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MemoryConfirmScreen(ApprovalScreen):
    """Review one memory operation before local access or persistence."""

    CSS = DECISION_CSS + """
    MemoryConfirmScreen { align: center middle; background: #000000 58%; }
    #memory-confirm-card { width: 96; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, details: str) -> None:
        super().__init__()
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-pack-card", classes="isy-dialog"):
            yield Static(tr("Workspace context pack · review before reading"),
                         id="workspace-pack-title", classes="isy-dialog-title")
            with VerticalScroll(id="workspace-pack-body", classes="isy-dialog-body"):
                yield Static(
                    Text("The listed files will be read and their contents returned to the selected model. "
                         "The token count is approximate. File contents are untrusted data, never instructions."),
                    id="workspace-pack-warning",
                )
                with Vertical(id="workspace-pack-files", classes="isy-dialog-detail"):
                    yield Static(Text(self.details))
            with Horizontal(id="workspace-pack-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="workspace-pack-cancel")
                yield Button(tr("Read and send once · y"), id="workspace-pack-approve",
                             variant="warning")
            yield decision_hint()

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
        with Vertical(id="memory-confirm-card", classes="isy-dialog"):
            yield Static(f"Workspace memory · {self.operation}", id="memory-confirm-title", classes="isy-dialog-title")
            with VerticalScroll(id="memory-confirm-body", classes="isy-dialog-body"):
                yield Static(Text(warning), id="memory-confirm-warning")
                with Vertical(id="memory-confirm-payload", classes="isy-dialog-detail"):
                    yield Static(Text(self.details))
            with Horizontal(id="memory-confirm-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="memory-confirm-cancel")
                yield Button(tr("Approve once · y"), id="memory-confirm-approve", variant="warning")
            yield decision_hint()

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

    CSS = DECISION_CSS + """
    DeleteSessionScreen { align: center middle; background: #000000 58%; }
    #delete-session-card { width: 72; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, *, kind: str = "conversation") -> None:
        super().__init__()
        self.title_text = title
        self.kind = kind if kind == "iteration" else "conversation"

    def compose(self) -> ComposeResult:
        if self.kind == "iteration":
            heading = tr("Delete this iteration?")
            button = tr("Delete iteration · y")
            detail = tr("This permanently removes this one iteration ledger.")
        else:
            heading = tr("Delete this conversation?")
            button = tr("Delete conversation · y")
            detail = tr("This permanently removes this one transcript.")
        with Vertical(id="delete-session-card", classes="isy-dialog"):
            yield Static(heading, id="delete-session-title", classes="isy-dialog-title")
            with VerticalScroll(id="delete-session-body", classes="isy-dialog-body"):
                yield Static(tr("{title}\n\n{detail} A one-use, session-bound approval will be checked before deletion.",
                                title=self.title_text, detail=detail),
                             id="delete-session-copy")
            with Horizontal(id="delete-session-actions", classes="isy-dialog-actions"):
                yield Button(tr("Keep · n"), id="delete-session-cancel")
                yield Button(button, id="delete-session-confirm", variant="error")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#delete-session-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "delete-session-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
