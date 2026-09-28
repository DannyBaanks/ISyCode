"""Semantic command browser launched with the ``isycode cli`` entry point.

The tree points to views already implemented by ISyCode. It never launches a
shell command or creates a second authority for filesystem/tool operations.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Static, Tree


@dataclass(frozen=True)
class CLIAction:
    category: str
    name: str
    description: str
    view: str = "overview"
    prompt: str = ""


COMMAND_BRANCHES: tuple[tuple[str, tuple[CLIAction, ...]], ...] = (
    ("Agent", (
        CLIAction("Agent", "Chat", "Open a new conversation in ISyCode."),
        CLIAction("Agent", "Plan", "Draft an intent for IsyMotron to review.", prompt="/plan "),
        CLIAction("Agent", "External review", "Preview a text artifact and request one tool-free GPT-6 Luna review.", prompt="/review "),
        CLIAction("Agent", "Help", "Show the commands registered by ISyCode.", prompt="/help"),
        CLIAction("Agent", "Choose role", "Choose an ISyCode workspace role; this does not grant tools.", view="roles"),
    )),
    ("Workspace", (
        CLIAction("Workspace", "Browse files", "Open the logical workspace tree; reads remain grant and receipt gated.", view="files"),
        CLIAction("Workspace", "Preview README", "Open the Linux file chooser and preview a README inside the workspace.", prompt="/readme"),
        CLIAction("Workspace", "Workspace overview", "Show the logical root, launch directory, and integration status."),
    )),
    ("Integrations", (
        CLIAction("Integrations", "ISyCode integrations", "Open the MCP, skills, provider, and Gateway overview."),
        CLIAction("Integrations", "Refresh catalogs", "Refresh the connected ISyCode integration catalogs."),
    )),
    ("Providers", (
        CLIAction("Providers", "Choose provider", "Open ISyCode's provider selector and configure credentials in the OS vault.", view="providers"),
        CLIAction("Providers", "Provider status", "Show provider and credential status without revealing secrets.", prompt="/providers"),
    )),
    ("Session", (
        CLIAction("Session", "New conversation", "Start a named conversation saved for this workspace."),
        CLIAction("Session", "Session status", "Show the current provider, model, and selected role.", view="session"),
    )),
    ("Settings", (
        CLIAction("Settings", "Commands and shortcuts", "Open the shortcut reference and workspace controls.", view="settings"),
        CLIAction("Settings", "Select chat role", "Choose conversational guidance for the active workspace.", view="roles"),
    )),
)


class CommandBrowser(App[None]):
    """Navigate available actions as semantic folders rather than shell flags."""

    TITLE = "ISyCo CLI"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #111116; }
    #cli-header { dock: top; height: 3; padding: 1 2; background: #201e26; color: #bb8cff; text-style: bold; }
    #cli-body { height: 1fr; padding: 1 2; }
    #command-navigation { width: 38; height: 1fr; }
    #command-search { height: 3; margin-bottom: 1; }
    #command-tree { width: 1fr; height: 1fr; border: round #383541; background: #17161d; padding: 1; }
    #selection-panel { width: 1fr; height: 1fr; margin-left: 1; padding: 1 2; border: round #383541; background: #17161d; }
    #selection-title { height: 2; color: #bb8cff; text-style: bold; }
    #selection-path { height: 2; color: #85849a; }
    #selection-description { height: 1fr; color: #e6e3ee; }
    #open-selection { width: 24; height: 3; dock: bottom; }
    Footer { background: #111116; color: #85849a; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_action: CLIAction | None = None

    def compose(self) -> ComposeResult:
        yield Static("ISYCO CLI  ·  COMMANDS BY INTENT", id="cli-header")
        with Horizontal(id="cli-body"):
            with Vertical(id="command-navigation"):
                yield Input(placeholder="Search actions…", id="command-search")
                yield Tree("Command branches", id="command-tree")
            with Vertical(id="selection-panel"):
                yield Static("Choose an action", id="selection-title")
                yield Static("Agent / Workspace / Integrations / Providers / Session / Settings", id="selection-path")
                yield Static(
                    "Search by action or description. Use ↑/↓ to move, ←/→ to collapse or expand, "
                    "Enter to inspect, then choose Open selected.", id="selection-description",
                )
                yield Button("Open selected", id="open-selection", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_tree()
        self.query_one("#command-search", Input).focus()

    def _rebuild_tree(self, query: str = "") -> None:
        tree = self.query_one("#command-tree", Tree)
        tree.root.remove_children()
        tree.show_root = False
        for category, actions in COMMAND_BRANCHES:
            matching = tuple(action for action in actions if not query or query in " ".join((
                action.category, action.name, action.description,
            )).casefold())
            if not matching:
                continue
            branch = tree.root.add(f"📁 {category}")
            for action in matching:
                branch.add_leaf(f"›  {action.name}", data=action)
            branch.expand()
        tree.root.expand()
        if query:
            self.selected_action = None
            self.query_one("#open-selection", Button).disabled = True
            self.query_one("#selection-title", Static).update("Search results")
            self.query_one("#selection-path", Static).update(query)
            self.query_one("#selection-description", Static).update(
                "Matching semantic actions are shown in the tree. Select a leaf to inspect it.")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-search":
            self._rebuild_tree(event.value.strip().casefold())

    def on_key(self, event) -> None:
        if event.key != "escape":
            return
        search = self.query_one("#command-search", Input)
        if search.value:
            search.value = ""
            search.focus()
        else:
            self.exit()
        event.stop()

    async def action_back(self) -> None:
        self.exit()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        action = event.node.data
        if not isinstance(action, CLIAction):
            return
        self.selected_action = action
        self.query_one("#selection-title", Static).update(action.name)
        self.query_one("#selection-path", Static).update(f"{action.category}  /  {action.name}")
        self.query_one("#selection-description", Static).update(action.description)
        self.query_one("#open-selection", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-selection" and self.selected_action is not None:
            self.exit()


def main(argv: list[str] | None = None) -> None:
    """Run the semantic command browser for ``isyco cli``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["cli"]:
        print("Usage: isyco cli")
        return

    browser = CommandBrowser()
    browser.run()
    if browser.selected_action is None:
        return

    # Import only after the user opens an action, keeping startup lightweight.
    from isycode.tui import TUIApp

    action = browser.selected_action
    TUIApp(initial_view=action.view, initial_prompt=action.prompt).run()
