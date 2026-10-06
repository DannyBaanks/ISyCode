"""Workspace, grant, and credential modals.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Button, Input, OptionList, Static
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets.option_list import Option
from pathlib import Path
from isycode.workspace_setup import broad_workspace_reason



class WorkspaceSetupScreen(ModalScreen[bool]):
    """Ask once before marking this launch directory as a recurring workspace."""

    CSS = """
    WorkspaceSetupScreen { align: center middle; background: #000000 58%; }
    #workspace-setup-card { width: 76; max-width: 90%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #workspace-setup-title { height: 2; color: #bb8cff; text-style: bold; }
    #workspace-setup-copy { height: auto; margin-bottom: 1; color: #d7d5dc; }
    #workspace-setup-options { height: 5; margin-bottom: 1; }
    #workspace-setup-actions { height: 3; align-horizontal: right; }
    #workspace-setup-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "decline", "Not now"),
                Binding("ctrl+c", "decline", "Not now", show=False)]

    def __init__(self, launch_dir: Path) -> None:
        super().__init__()
        self.launch_dir = launch_dir

    def compose(self) -> ComposeResult:
        broad = broad_workspace_reason(self.launch_dir)
        warning = ("" if broad is None else
                   f"Caution: {broad}. A marker here would make every folder below it without "
                   "its own .isyroot share this workspace's grants and sessions. Your "
                   "'recurring' default is not applied here.\n\n")
        with Vertical(id="workspace-setup-card"):
            yield Static("Set up this workspace?", id="workspace-setup-title")
            yield Static(
                f"Launch directory:\n{self.launch_dir}\n\n{warning}"
                "If this is a recurring project, Yes creates an empty .isyroot here and saves chat "
                "sessions in your private ISyCode state directory. .isyroot identifies the workspace; "
                "it does not grant filesystem access. Not now keeps this run temporary, and its chat "
                "history is removed when ISyCode exits.", id="workspace-setup-copy")
            yield OptionList(
                Option("Yes · recurring workspace", id="yes"),
                Option("No · temporary run", id="no"),
                id="workspace-setup-options")
            with Horizontal(id="workspace-setup-actions"):
                yield Button("Yes, remember this workspace", id="workspace-setup-yes", variant="primary")
                yield Button("No, keep it temporary", id="workspace-setup-no")

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


class GlobalRecurringDefaultScreen(ModalScreen[bool]):
    """Confirm a user-wide preference that creates .isyroot in future folders."""

    CSS = """
    GlobalRecurringDefaultScreen { align: center middle; background: #000000 58%; }
    #global-recurring-card { width: 76; max-width: 90%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #global-recurring-title { height: 2; color: #bb8cff; text-style: bold; }
    #global-recurring-copy { height: auto; margin-bottom: 1; }
    #global-recurring-actions { height: 3; align-horizontal: right; }
    #global-recurring-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="global-recurring-card"):
            yield Static("Use recurring mode for new folders?", id="global-recurring-title")
            yield Static(
                "When ISyCode first opens a folder without a saved choice, it will create an empty "
                ".isyroot marker there. This remembers the workspace identity only; it does not "
                "grant file access or copy permissions from another workspace. Broad folders such as "
                "your home directory, its parents, the temporary directory, or a mount point still ask "
                "first, so unrelated projects never share one workspace by accident.",
                id="global-recurring-copy")
            with Horizontal(id="global-recurring-actions"):
                yield Button("Cancel", id="global-recurring-cancel")
                yield Button("Use for new folders", id="global-recurring-confirm", variant="primary")

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

    CSS = """
    QuickStartScreen { align: center middle; background: #000000 58%; }
    #quick-start-card { width: 84; max-width: 94%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #quick-start-title { height: 2; color: #bb8cff; text-style: bold; }
    #quick-start-copy { height: auto; margin-bottom: 1; }
    #quick-start-options { height: 4; }
    """
    BINDINGS = [Binding("escape", "custom", "Custom setup")]

    def __init__(self, root: Path, *, provider_ready: bool) -> None:
        super().__init__()
        self.root = root
        self.provider_ready = provider_ready

    def compose(self) -> ComposeResult:
        provider_line = ("Your provider key is already in the environment, so chat works right away."
                         if self.provider_ready else
                         "No provider key detected yet; you can add one later in Settings → Providers.")
        with Vertical(id="quick-start-card"):
            yield Static("Welcome to ISyCode · how do you want to start?",
                         id="quick-start-title")
            yield Static(
                f"{self.root}\n\n{provider_line}\n\n"
                "Quick Start: this folder becomes a recurring workspace in Classic mode — "
                "read/search, edit proposals and chat are ready. One more confirmation can turn on "
                "all coding tools, and edits, commands and commits still ask until you approve them.\n"
                "Custom setup: choose recurrence, Classic or Security, and each tool step by step.\n\n"
                "Both paths keep IsySentinel and the action journal on everything.",
                id="quick-start-copy")
            yield OptionList(
                Option("Quick Start · ready in under a minute", id="quick"),
                Option("Custom setup · choose each step", id="custom"),
                id="quick-start-options")

    def on_mount(self) -> None:
        self.query_one("#quick-start-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss("quick" if event.option.id == "quick" else "custom")

    def action_custom(self) -> None:
        self.dismiss("custom")


class WorkspaceModeScreen(ModalScreen[str]):
    """Choose how a new workspace starts: Classic (ready to use) or Security."""

    CSS = """
    WorkspaceModeScreen { align: center middle; background: #000000 58%; }
    #workspace-mode-card { width: 84; max-width: 94%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #workspace-mode-title { height: 2; color: #bb8cff; text-style: bold; }
    #workspace-mode-copy { height: auto; margin-bottom: 1; }
    #workspace-mode-options { height: 4; }
    """
    BINDINGS = [Binding("escape", "security", "Security")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-mode-card"):
            yield Static("How should ISyCode work in this folder?", id="workspace-mode-title")
            yield Static(
                f"{self.root}\n\nClassic: ready to code. Read/search, edit proposals, chat, saved sessions, Git review and sandboxed commands (when available) are ready. "
                "A separate confirmation can trust this folder so ordinary edits and isolated tests stop asking one by one. "
                "Until you confirm that, each edit, delete/move, command and commit still asks. "
                "Commits, secrets and authority changes keep asking either way.\n"
                "Security: nothing is allowed until you turn it on in Settings → Authority.\n\n"
                "Both modes use IsySentinel and the action journal. "
                "Free shell and sensitive files are never implied. Switch any time "
                "in Settings → Authority.", id="workspace-mode-copy")
            yield OptionList(
                Option("Classic · Ready To Use", id="classic"),
                Option("Security · everything off until I allow it", id="security"),
                id="workspace-mode-options")

    def on_mount(self) -> None:
        self.query_one("#workspace-mode-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss("classic" if event.option.id == "classic" else "security")

    def action_security(self) -> None:
        self.dismiss("security")


class GrantWorkspaceReadScreen(ModalScreen[bool]):
    """Explicitly grant only bounded, read-only workspace tools."""

    CSS = """
    GrantWorkspaceReadScreen { align: center middle; background: #000000 58%; }
    #workspace-read-card { width: 82; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #workspace-read-title { height: 2; color: #bb8cff; text-style: bold; }
    #workspace-read-copy { height: auto; margin-bottom: 1; }
    #workspace-read-actions { height: 3; align-horizontal: right; }
    #workspace-read-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, *, revoke: bool = False) -> None:
        super().__init__()
        self.root = root
        self.revoke = revoke

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-read-card"):
            yield Static("Turn off file reading?" if self.revoke
                         else "Allow ISyCode to read workspace files?", id="workspace-read-title")
            copy = ("ISyCode will stop listing, reading, and searching files in this workspace. "
                    "Your files and conversations stay where they are."
                    if self.revoke else
                    "ISyCode can list folders, read text files, find file names, and use a chosen AGENTS.md "
                    "to understand your project. It cannot edit or delete files, run commands, or access "
                    "folders outside this workspace. You will still be asked before sensitive actions.")
            yield Static(copy, id="workspace-read-copy")
            with Horizontal(id="workspace-read-actions"):
                yield Button("Cancel", id="workspace-read-cancel")
                yield Button("Turn off" if self.revoke else "Turn on",
                             id="workspace-read-grant", variant="error" if self.revoke else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "workspace-read-grant")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantProviderNetworkScreen(ModalScreen[bool]):
    """Confirm network authority for one provider endpoint host."""

    CSS = """
    GrantProviderNetworkScreen { align: center middle; background: #000000 58%; }
    #provider-network-card { width: 82; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #provider-network-title { height: 2; color: #bb8cff; text-style: bold; }
    #provider-network-copy { height: auto; margin-bottom: 1; }
    #provider-network-actions { height: 3; align-horizontal: right; }
    #provider-network-actions Button { margin-left: 1; }
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
        with Vertical(id="provider-network-card"):
            yield Static("Turn off this option?" if self.revoke else "Turn on this option?",
                         id="provider-network-title")
            yield Static(copy + "\n\nHost: " + self.host, id="provider-network-copy")
            with Horizontal(id="provider-network-actions"):
                yield Button("Cancel", id="provider-network-cancel")
                yield Button("Turn off" if self.revoke else "Turn on", id="provider-network-confirm",
                             variant="error" if self.revoke else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "provider-network-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantMCPInvocationScreen(ModalScreen[bool]):
    """Grant the Gateway MCP server as a target; every call still needs approval."""

    CSS = """
    GrantMCPInvocationScreen { align: center middle; background: #000000 58%; }
    #mcp-grant-card { width: 82; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #mcp-grant-title { height: 2; color: #bb8cff; text-style: bold; }
    #mcp-grant-copy { height: auto; margin-bottom: 1; }
    #mcp-grant-actions { height: 3; align-horizontal: right; }
    #mcp-grant-actions Button { margin-left: 1; }
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
        with Vertical(id="mcp-grant-card"):
            yield Static("Turn off Gateway tools?" if self.revoke else "Allow Gateway tools?",
                         id="mcp-grant-title")
            yield Static(copy, id="mcp-grant-copy")
            with Horizontal(id="mcp-grant-actions"):
                yield Button("Cancel", id="mcp-grant-cancel")
                yield Button("Turn off" if self.revoke else "Turn on", id="mcp-grant-confirm",
                             variant="error" if self.revoke else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "mcp-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GrantLSPProcessScreen(ModalScreen[bool]):
    """Consent to the fixed bubblewrap LSP owner and its exact executable."""

    CSS = """
    GrantLSPProcessScreen { align: center middle; background: #000000 58%; }
    #lsp-grant-card { width: 84; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #lsp-grant-title { height: 2; color: #bb8cff; text-style: bold; }
    #lsp-grant-copy { height: auto; margin-bottom: 1; }
    #lsp-grant-actions { height: 3; align-horizontal: right; }
    #lsp-grant-actions Button { margin-left: 1; }
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
        with Vertical(id="lsp-grant-card"):
            yield Static("Turn off local code help?" if self.revoke else "Allow local code help?",
                         id="lsp-grant-title")
            yield Static(copy, id="lsp-grant-copy")
            with Horizontal(id="lsp-grant-actions"):
                yield Button("Cancel", id="lsp-grant-cancel")
                yield Button("Turn off" if self.revoke else "Turn on", id="lsp-grant-confirm",
                             variant="error" if self.revoke else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "lsp-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrokerPreviewGrantScreen(ModalScreen[bool]):
    """Ask before persisting the narrow permission to inspect a broker plan."""

    CSS = """
    BrokerPreviewGrantScreen { align: center middle; background: #000000 58%; }
    #broker-grant-card { width: 82; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #broker-grant-title { height: 2; color: #bb8cff; text-style: bold; }
    #broker-grant-copy { height: auto; margin-bottom: 1; }
    #broker-grant-actions { height: 3; align-horizontal: right; }
    #broker-grant-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id="broker-grant-card"):
            yield Static("Allow semantic broker preview?", id="broker-grant-title")
            yield Static(
                f"Workspace: {self.root}\n\nThis stores only the broker.preview grant for this .isyroot. "
                "The selected project still needs its own workspace.files.read grant. "
                "Preview reads recipe metadata and hashes, does not launch Docker, and cannot start a container.",
                id="broker-grant-copy")
            with Horizontal(id="broker-grant-actions"):
                yield Button("Cancel", id="broker-grant-cancel")
                yield Button("Grant preview", id="broker-grant-confirm", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "broker-grant-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class AddCredentialScreen(ModalScreen[dict[str, str] | None]):
    """Capture a labelled API key without echoing it into the chat history."""

    CSS = """
    AddCredentialScreen { align: center middle; background: #000000 58%; }
    #credential-form { width: 76; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #credential-form-title { height: 2; color: #c7b8d4; text-style: bold; }
    #credential-form-help { height: auto; color: #b8b8bd; padding-bottom: 1; }
    #credential-form Input { height: 3; margin-bottom: 1; }
    #credential-form-actions { height: 3; align-horizontal: right; }
    #credential-form-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="credential-form"):
            yield Static("Add a named API key", id="credential-form-title")
            yield Static(
                "Saved in the operating system keyring and never shown after saving. "
                "Use service id `isyco-gateway` to supply the Gateway MCP.",
                id="credential-form-help")
            yield Input(placeholder="Name shown in Settings", id="credential-name")
            yield Input(placeholder="Service id, e.g. isyco-gateway", id="credential-service")
            yield Input(placeholder="Purpose / where this key is used", id="credential-purpose")
            yield Input(placeholder="Paste API key…", password=True, id="credential-secret")
            with Horizontal(id="credential-form-actions"):
                yield Button("Cancel", id="credential-cancel")
                yield Button("Save key", id="credential-save", variant="primary")

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
