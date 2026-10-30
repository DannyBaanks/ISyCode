"""Workspace, grant, and credential modals.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Button, Input, OptionList, Static
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets.option_list import Option
from pathlib import Path
from isycode.workspace_setup import broad_workspace_reason
from isycode.tui_screens_approval import ApprovalScreen, DECISION_CSS, decision_hint
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction



class OnboardingCopy(VerticalScroll):
    """Keyboard-scrollable explanation without pushing choices off-screen."""

    def __init__(self, content, **kwargs):
        super().__init__(Static(content, markup=False), can_focus=True, **kwargs)


class WorkspaceSetupScreen(ModalScreen[bool]):
    """Ask once before marking this launch directory as a recurring workspace."""

    CSS = DECISION_CSS + """
    WorkspaceSetupScreen { align: center middle; background: #000000 58%; }
    #workspace-setup-card { width: 76; }
    #workspace-setup-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "decline", "Not now"),
                Binding("ctrl+c", "decline", "Not now", show=False)]

    def __init__(self, launch_dir: Path) -> None:
        super().__init__()
        self.launch_dir = launch_dir

    def compose(self) -> ComposeResult:
        broad = broad_workspace_reason(self.launch_dir)
        warning = ("" if broad is None else
                   tr("Caution: {reason}. A marker here would make every folder below it without "
                      "its own .isyroot share this workspace's grants and sessions. Your "
                      "'recurring' default is not applied here.\n\n", reason=broad))
        with Vertical(id="workspace-setup-card", classes="isy-dialog"):
            yield Static(tr("Set up this workspace?"), id="workspace-setup-title", classes="isy-dialog-title")
            yield OnboardingCopy(
                tr("Launch directory:\n{path}\n\n{warning}"
                   "If this is a recurring project, Yes creates an empty .isyroot here and saves chat "
                   "sessions in your private ISyCode state directory. .isyroot identifies the workspace; "
                   "it does not grant filesystem access. Not now keeps this run temporary, and its chat "
                   "history is removed when ISyCode exits.",
                   path=str(self.launch_dir), warning=warning),
                id="workspace-setup-copy", classes="isy-dialog-body")
            yield OptionList(
                Option(tr("Yes · recurring workspace"), id="yes"),
                Option(tr("No · temporary run"), id="no"),
                id="workspace-setup-options", classes="isy-dialog-options")
            with Horizontal(id="workspace-setup-actions", classes="isy-dialog-actions"):
                yield Button(tr("Yes, remember this workspace"), id="workspace-setup-yes", variant="primary")
                yield Button(tr("No, keep it temporary"), id="workspace-setup-no")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#workspace-setup-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "yes":
            self.dismiss(True)
        elif event.option.id == "no":
            self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workspace-setup-yes":
            self.dismiss(True)
        elif event.button.id == "workspace-setup-no":
            self.dismiss(False)

    def action_decline(self) -> None:
        self.dismiss(False)


class GlobalRecurringDefaultScreen(ApprovalScreen):
    """Confirm a user-wide preference that creates .isyroot in future folders."""

    CSS = DECISION_CSS + """
    GlobalRecurringDefaultScreen { align: center middle; background: #000000 58%; }
    #global-recurring-card { width: 76; }
    #global-recurring-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="global-recurring-card", classes="isy-dialog"):
            yield Static(tr("Use recurring mode for new folders?"), id="global-recurring-title", classes="isy-dialog-title")
            with VerticalScroll(id="global-recurring-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="workspace setup preference", scope="future folders without a saved choice",
                    duration="persistent user preference",
                    not_granted="no file access, no permissions copied between workspaces")
                yield Static(tr("When ISyCode first opens a folder without a saved choice, it will create an empty "
                    ".isyroot marker there. This remembers the workspace identity only; it does not "
                    "grant file access or copy permissions from another workspace. Broad folders such as "
                    "your home directory, its parents, the temporary directory, or a mount point still ask "
                    "first, so unrelated projects never share one workspace by accident."),
                    id="global-recurring-copy")
            with Horizontal(id="global-recurring-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="global-recurring-cancel", classes="-refuse")
                yield Button(tr("Use for new folders · y"), id="global-recurring-confirm", variant="primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "global-recurring-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class QuickStartScreen(ModalScreen[str]):
    """First-run fork: guided Quick Start or the step-by-step Custom setup.

    Dismisses with "quick" or "custom". Quick Start still asks its own
    explicit confirmations later (coding tools, trust); it only skips
    re-asking the mode and recurrence questions it already answered.
    """

    CSS = DECISION_CSS + """
    QuickStartScreen { align: center middle; background: #000000 58%; }
    #quick-start-card { width: 84; }
    #quick-start-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "custom", "Custom setup")]

    def __init__(self, root: Path, *, provider_ready: bool) -> None:
        super().__init__()
        self.root = root
        self.provider_ready = provider_ready

    def compose(self) -> ComposeResult:
        provider_line = (tr("Your provider key is already in the environment, so chat works right away.")
                         if self.provider_ready else
                         tr("No provider key detected yet; you can add one later in Settings → Providers."))
        with Vertical(id="quick-start-card", classes="isy-dialog"):
            yield Static(tr("Welcome to ISyCode · how do you want to start?"),
                         id="quick-start-title", classes="isy-dialog-title")
            yield OnboardingCopy(
                tr("{root}\n{provider_line}\n"
                   "Quick Start: this folder becomes a recurring Classic workspace — read/search, "
                   "edit proposals and chat are ready. One more confirmation turns on all coding "
                   "tools; edits, commands and commits still ask until you approve them.\n"
                   "Custom setup: choose recurrence, Classic or Security, and each tool step by step.\n"
                   "Both paths keep IsySentinel and the action journal on everything.",
                   root=str(self.root), provider_line=provider_line),
                id="quick-start-copy", classes="isy-dialog-body")
            yield OptionList(
                Option(tr("Quick Start · ready in under a minute"), id="quick"),
                Option(tr("Custom setup · choose each step"), id="custom"),
                id="quick-start-options", classes="isy-dialog-options")
            with Horizontal(id="quick-start-actions", classes="isy-dialog-actions"):
                yield Button(tr("Custom setup"), id="quick-start-custom")
                yield Button(tr("Continue"), id="quick-start-continue", variant="primary")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#quick-start-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss("quick" if event.option.id == "quick" else "custom")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "quick-start-custom":
            self.dismiss("custom")
        elif event.button.id == "quick-start-continue":
            options = self.query_one("#quick-start-options", OptionList)
            choice = options.get_option_at_index(options.highlighted or 0)
            self.dismiss("quick" if choice.id == "quick" else "custom")

    def action_custom(self) -> None:
        self.dismiss("custom")


class WorkspaceModeScreen(ModalScreen[str]):
    """Choose how a new workspace starts: Classic (ready to use) or Security."""

    CSS = DECISION_CSS + """
    WorkspaceModeScreen { align: center middle; background: #000000 58%; }
    #workspace-mode-card { width: 84; }
    #workspace-mode-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "security", "Security")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-mode-card", classes="isy-dialog"):
            yield Static(tr("How should ISyCode work in this folder?"), id="workspace-mode-title", classes="isy-dialog-title")
            yield self._mode_copy()
            yield OptionList(
                Option(tr("Classic · recommended"), id="classic"),
                Option(tr("Flow · recoverable local work without questions"), id="flow"),
                Option(tr("Security · everything off until I allow it"), id="security"),
                id="workspace-mode-options", classes="isy-dialog-options")
            with Horizontal(id="workspace-mode-actions", classes="isy-dialog-actions"):
                yield Button(tr("Security"), id="workspace-mode-security")
                yield Button(tr("Continue"), id="workspace-mode-continue", variant="primary")
            yield decision_hint()

    def _mode_copy(self) -> OnboardingCopy:
        return OnboardingCopy(
            tr("{root}\nClassic (recommended): review edits and commands, or trust this folder for quiet local work.\n"
               "Flow: edits, moves, deletes and sandboxed shell commands run without questions. "
               "Each chat turn is recorded; /undo restores its files while keeping later human changes. "
               "Commits of this turn's own files can run quietly.\n"
               "Security: everything off until you allow it.\n"
               "All modes keep Sentinel, budgets and receipts. Push, secrets, integrations and authority "
               "changes still ask or stay off. Flow commands need a verified sandbox; command network stays off.",
               root=str(self.root)),
            id="workspace-mode-copy", classes="isy-dialog-body")

    def on_mount(self) -> None:
        self.query_one("#workspace-mode-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id if event.option.id in {"classic", "flow", "security"} else "security")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "workspace-mode-security":
            self.dismiss("security")
        elif event.button.id == "workspace-mode-continue":
            options = self.query_one("#workspace-mode-options", OptionList)
            choice = options.get_option_at_index(options.highlighted or 0)
            self.dismiss(choice.id if choice.id in {"classic", "flow", "security"} else "security")

    def action_security(self) -> None:
        self.dismiss("security")


class WorkspaceModeSwitchScreen(WorkspaceModeScreen):
    """Switch an open workspace between Classic, Flow and Security.

    Opened from the bottom-bar mode chip. Escape and Cancel keep the current
    mode; the caller confirms and performs the switch through the same path
    as Settings → Authority → Workflow.
    """

    BINDINGS = [Binding("escape", "cancel", "Back")]
    _LABELS = {
        "classic": "Classic · recommended",
        "flow": "Flow · recoverable local work without questions",
        "security": "Security · everything off until I allow it",
    }

    def __init__(self, root: Path, current: str) -> None:
        super().__init__(root)
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-mode-card", classes="isy-dialog"):
            yield Static(tr("Workflow"), id="workspace-mode-title", classes="isy-dialog-title")
            yield self._mode_copy()
            yield OptionList(*(
                Option(tr("{mode} · current", mode=tr(label)) if mode == self.current else tr(label), id=mode)
                for mode, label in self._LABELS.items()),
                id="workspace-mode-options", classes="isy-dialog-options")
            with Horizontal(id="workspace-mode-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="workspace-mode-cancel")
                yield Button(tr("Continue"), id="workspace-mode-continue", variant="primary")
            yield decision_hint()

    def on_mount(self) -> None:
        options = self.query_one("#workspace-mode-options", OptionList)
        options.highlighted = list(self._LABELS).index(self.current) if self.current in self._LABELS else 0
        options.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Textual dispatches this handler through every class in the MRO.
        # Without prevent_default the parent would dismiss a second time.
        event.prevent_default()
        if event.button.id == "workspace-mode-cancel":
            event.stop()
            self.dismiss(None)
            return
        super().on_button_pressed(event)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GrantWorkspaceReadScreen(ApprovalScreen):
    """Explicitly grant only bounded, read-only workspace tools."""

    CSS = DECISION_CSS + """
    GrantWorkspaceReadScreen { align: center middle; background: #000000 58%; }
    #workspace-read-card { width: 82; }
    #workspace-read-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, *, revoke: bool = False) -> None:
        super().__init__()
        self.root = root
        self.revoke = revoke

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-read-card", classes="isy-dialog"):
            yield Static(tr("Turn off file reading?") if self.revoke
                         else tr("Allow ISyCode to read workspace files?"), id="workspace-read-title", classes="isy-dialog-title")
            with VerticalScroll(id="workspace-read-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="workspace file read", scope=str(self.root),
                    duration="persistent grant (until revoked)",
                    not_granted="no edits, no commands, no folders outside workspace")
                yield Static(tr("Folder: {root}\n", root=self.root), markup=False)
                copy = (tr("ISyCode will stop listing, reading, and searching files in this workspace. "
                           "Your files and conversations stay where they are.")
                        if self.revoke else
                        tr("ISyCode can list folders, read text files, find file names, and use a chosen AGENTS.md "
                           "to understand your project. It cannot edit or delete files, run commands, or access "
                           "folders outside this workspace. You will still be asked before sensitive actions."))
                yield Static(copy, id="workspace-read-copy")
            with Horizontal(id="workspace-read-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="workspace-read-cancel", classes="-refuse")
                yield Button(tr("Turn off · y") if self.revoke else tr("Turn on · y"),
                             id="workspace-read-grant", variant="error" if self.revoke else "primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "workspace-read-grant")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantProviderNetworkScreen(ApprovalScreen):
    """Confirm network authority for one provider endpoint host."""

    CSS = DECISION_CSS + """
    GrantProviderNetworkScreen { align: center middle; background: #000000 58%; }
    #provider-network-card { width: 82; }
    #provider-network-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, host: str, *, revoke: bool = False) -> None:
        super().__init__()
        self.label = label
        self.host = host
        self.revoke = revoke

    def compose(self) -> ComposeResult:
        copy = (f"Turn off {self.label}? Future requests will be blocked until you turn it on again."
                if self.revoke else
                f"Allow {self.label}? ISyCode will only send the information needed for this feature. "
                "Your saved key and access to workspace files are controlled separately.")
        if self.label == "Find Gateway tools" and not self.revoke:
            copy += " Finding tools does not run them."
        if self.label == "Search and understand code with Gateway" and not self.revoke:
            copy += " You review each search and approve it before it runs."
        with Vertical(id="provider-network-card", classes="isy-dialog"):
            yield Static(tr("Turn off this option?") if self.revoke else tr("Turn on this option?"),
                         id="provider-network-title", classes="isy-dialog-title")
            with VerticalScroll(id="provider-network-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="provider network access", scope=self.host,
                    duration="persistent grant (until revoked)",
                    not_granted="no tool execution, no file access, no secrets")
                yield Static(tr("{copy}\n\nHost: {host}", copy=copy, host=self.host), id="provider-network-copy", markup=False)
            with Horizontal(id="provider-network-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="provider-network-cancel", classes="-refuse")
                yield Button(tr("Turn off · y") if self.revoke else tr("Turn on · y"), id="provider-network-confirm",
                             variant="error" if self.revoke else "primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "provider-network-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantMCPInvocationScreen(ApprovalScreen):
    """Grant the Gateway MCP server as a target; every call still needs approval."""

    CSS = DECISION_CSS + """
    GrantMCPInvocationScreen { align: center middle; background: #000000 58%; }
    #mcp-grant-card { width: 82; }
    #mcp-grant-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, host: str, *, revoke: bool = False) -> None:
        super().__init__()
        self.host = host
        self.revoke = revoke

    def compose(self) -> ComposeResult:
        copy = ("ISyCode will stop running tools from your Gateway. Other settings and saved keys stay unchanged."
                if self.revoke else
                "ISyCode can run a tool you choose from your Gateway. You will see what it wants to do "
                "and approve every run before it starts.")
        with Vertical(id="mcp-grant-card", classes="isy-dialog"):
            yield Static(tr("Turn off Gateway tools?") if self.revoke else tr("Allow Gateway tools?"),
                         id="mcp-grant-title", classes="isy-dialog-title")
            with VerticalScroll(id="mcp-grant-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="Gateway MCP target", scope=self.host,
                    duration="persistent grant (every call still approved)",
                    not_granted="no automatic tool runs, no local filesystem access")
                yield Static(tr("Host: {host}", host=self.host), markup=False)
                yield Static(copy, id="mcp-grant-copy")
            with Horizontal(id="mcp-grant-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="mcp-grant-cancel", classes="-refuse")
                yield Button(tr("Turn off · y") if self.revoke else tr("Turn on · y"), id="mcp-grant-confirm",
                             variant="error" if self.revoke else "primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "mcp-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantLSPProcessScreen(ApprovalScreen):
    """Consent to the fixed bubblewrap LSP owner and its exact executable."""

    CSS = DECISION_CSS + """
    GrantLSPProcessScreen { align: center middle; background: #000000 58%; }
    #lsp-grant-card { width: 84; }
    #lsp-grant-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, sandbox_path: str, *, revoke: bool = False) -> None:
        super().__init__()
        self.root = root
        self.sandbox_executable = sandbox_path
        self.revoke = revoke

    def compose(self) -> ComposeResult:
        copy = ("ISyCode will stop using local code help. Other workspace options stay unchanged."
                if self.revoke else
                "ISyCode can use its protected local helper to find code symbols in this workspace. "
                "The helper cannot access the internet or run general commands. Reading files still "
                "follows the separate file access option.")
        with Vertical(id="lsp-grant-card", classes="isy-dialog"):
            yield Static(tr("Turn off local code help?") if self.revoke else tr("Allow local code help?"),
                         id="lsp-grant-title", classes="isy-dialog-title")
            with VerticalScroll(id="lsp-grant-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="local LSP process", scope=str(self.root),
                    duration="persistent grant (until revoked)",
                    not_granted="no internet, no general commands, no writes")
                yield Static(tr("Folder: {root}\n", root=self.root), markup=False)
                yield Static(self.sandbox_executable, markup=False)
                yield Static(copy, id="lsp-grant-copy")
            with Horizontal(id="lsp-grant-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="lsp-grant-cancel", classes="-refuse")
                yield Button(tr("Turn off · y") if self.revoke else tr("Turn on · y"), id="lsp-grant-confirm",
                             variant="error" if self.revoke else "primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "lsp-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrokerPreviewGrantScreen(ApprovalScreen):
    """Ask before persisting the narrow permission to inspect a broker plan."""

    CSS = DECISION_CSS + """
    BrokerPreviewGrantScreen { align: center middle; background: #000000 58%; }
    #broker-grant-card { width: 82; }
    #broker-grant-card { max-height: 30; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id="broker-grant-card", classes="isy-dialog"):
            yield Static(tr("Allow semantic broker preview?"), id="broker-grant-title", classes="isy-dialog-title")
            with VerticalScroll(id="broker-grant-body", classes="isy-dialog-body"):
                yield self._structural_summary(
                    owner="broker preview", scope=str(self.root),
                    duration="persistent grant (until revoked)",
                    not_granted="no Docker, no containers, no workspace.files.read")
                yield Static(
                    tr("Workspace: {root}\n\nThis stores only the broker.preview grant for this .isyroot. The selected project still needs its own workspace.files.read grant. Preview reads recipe metadata and hashes, does not launch Docker, and cannot start a container.", root=self.root),
                    id="broker-grant-copy")
            with Horizontal(id="broker-grant-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · n"), id="broker-grant-cancel", classes="-refuse")
                yield Button(tr("Grant preview · y"), id="broker-grant-confirm", variant="primary")
            yield decision_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "broker-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class AddCredentialScreen(ModalScreen[dict[str, str] | None]):
    """Capture a labelled API key without echoing it into the chat history."""

    CSS = DECISION_CSS + """
    AddCredentialScreen { align: center middle; background: #000000 58%; }
    #credential-form { width: 76; }
    #credential-form Input { height: 3; margin-bottom: 1; background: #000000; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="credential-form", classes="isy-dialog"):
            yield Static(tr("Add a named API key"), id="credential-form-title", classes="isy-dialog-title")
            with VerticalScroll(id="credential-body", classes="isy-dialog-body"):
                yield Static(tr("Saved in the operating system keyring and never shown after saving. "
                    "Use service id `isyco-gateway` to supply the Gateway MCP."),
                    id="credential-form-help")
                yield Input(placeholder=tr("Name shown in Settings"), id="credential-name")
                yield Input(placeholder=tr("Service id, e.g. isyco-gateway"), id="credential-service")
                yield Input(placeholder=tr("Purpose / where this key is used"), id="credential-purpose")
                yield Input(placeholder=tr("Paste API key…"), password=True, id="credential-secret")
            with Horizontal(id="credential-form-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="credential-cancel")
                yield Button(tr("Save key"), id="credential-save", variant="primary")
            yield decision_hint()

    def on_mount(self) -> None:
        self.query_one("#credential-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "credential-save":
            self.dismiss({
                "name": self.query_one("#credential-name", Input).value,
                "service": self.query_one("#credential-service", Input).value,
                "purpose": self.query_one("#credential-purpose", Input).value,
                "secret": self.query_one("#credential-secret", Input).value,
            })
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProviderKeyScreen(Dialog):
    """Ask for a provider's API key: where to create it, then one masked field.

    Returns the pasted text, or None. The field keeps the id the clipboard
    guard refuses to copy from, and is emptied before the screen closes.
    Saving still goes through the credential owner and its confirmation.
    Without an OS keyring (``keyring=False``) the dialog says so before the
    paste, and its action keeps the key for this session only.
    """

    dialog_width = "normal"
    dialog_cancel_result = None

    def __init__(self, label: str, *, url: str = "", note: str = "", env: str = "",
                 keyring: bool = True) -> None:
        self.label = label
        self.url = url
        self.note = note
        self.env = env
        self.keyring = keyring
        super().__init__(id="provider-key")

    def dialog_heading(self) -> str:
        return tr("Connect {name}", name=self.label)

    def dialog_note(self) -> str:
        lines = [tr("{name} needs an API key before ISyCode can list its models or chat.",
                    name=self.label), ""]
        if self.url:
            lines += [tr("1. Open {url} and sign in.", url=self.url),
                      tr("2. Create an API key and copy it. Most consoles show it only once."),
                      tr("3. Paste it below and choose Save key.") if self.keyring
                      else tr("3. Paste it below and choose Use for this session.")]
        else:
            lines.append(tr("Paste the key below and choose Save key.") if self.keyring
                         else tr("Paste the key below and choose Use for this session."))
        if self.note:
            lines += ["", tr(self.note)]
        if not self.keyring:
            # After the steps: getting the key matters first, where it lives second.
            lines += ["", tr("No secure OS keyring is available on this machine, so the key cannot be "
                             "saved. It can still be used for this session; you will paste it again "
                             "next time.")]
        if self.env:
            lines += ["", tr("You can also set {env} in your environment and restart ISyCode.",
                             env=self.env)]
        return "\n".join(lines)

    def dialog_hint(self) -> str:
        if not self.keyring:
            return tr("Kept in memory for this run only; never written to disk, this project, "
                      "its logs or the chat.")
        return tr("Saved in your OS keyring for your user; never in this project, its logs or the chat.")

    def compose_body(self) -> ComposeResult:
        yield Input(placeholder=tr("Paste API key…"), password=True, id="provider-key-input")
        yield Static("", id="provider-key-error", markup=False)

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        actions = [DialogAction("provider-key-cancel", tr("Cancel"))]
        if self.url:
            actions.append(DialogAction("provider-key-open", tr("Open page")))
        actions.append(DialogAction("provider-key-save",
                                    tr("Save key") if self.keyring else tr("Use for this session"),
                                    "primary"))
        return tuple(actions)

    def on_mount(self, event) -> None:
        # The frame would focus the first action; a key dialog starts in its field.
        event.prevent_default()
        # The field is absent only if the app closes while this dialog mounts.
        for field in self.query("#provider-key-input"):
            field.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._save()

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "provider-key-save":
            self._save()
        elif action_id == "provider-key-open":
            self.app.open_url(self.url)
        else:
            self._clear_and_dismiss(None)

    def action_cancel(self) -> None:
        self._clear_and_dismiss(None)

    def _save(self) -> None:
        field = self.query_one("#provider-key-input", Input)
        if not field.value.strip():
            error = self.query_one("#provider-key-error", Static)
            error.update(tr("Paste a key first."))
            error.display = True
            field.focus()
            return
        self._clear_and_dismiss(field.value.strip())

    def _clear_and_dismiss(self, result: str | None) -> None:
        self.query_one("#provider-key-input", Input).value = ""
        self.dismiss(result)
