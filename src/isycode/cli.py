"""Semantic command browser launched with the ``isycode cli`` entry point.

The tree points to views already implemented by ISyCode. It never launches a
shell command or creates a second authority for filesystem/tool operations.
"""
from __future__ import annotations

import sys
import unicodedata
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
        CLIAction("Agent", "Plan", "Draft a proposal through an authorized provider; execution is disabled in Secure.", prompt="/plan "),
        CLIAction("Agent", "External review", "Preview a text artifact and request one tool-free GPT-6 Luna review.", prompt="/review "),
        CLIAction("Agent", "Help", "Show the commands registered by ISyCode.", prompt="/help"),
        CLIAction("Agent", "Choose role", "Choose an ISyCode workspace role; this does not grant tools.", view="roles"),
    )),
    ("Workspace", (
        CLIAction("Workspace", "Browse files", "Open the logical workspace tree; reads remain grant and receipt gated.", view="files"),
        CLIAction("Workspace", "Preview README", "Open the file chooser and preview a README inside the workspace.", prompt="/readme"),
        CLIAction("Workspace", "Workspace overview", "Show the logical root, launch directory, and integration status."),
    )),
    ("Integrations", (
        CLIAction("Integrations", "ISyCode integrations", "Open the MCP, skills, provider, and Gateway overview."),
        CLIAction("Integrations", "Refresh catalogs", "Refresh the connected ISyCode integration catalogs."),
    )),
    ("Providers", (
        CLIAction("Providers", "Choose provider", "Open ISyCode's provider selector and configure credentials in the OS vault.", prompt="/providers"),
        CLIAction("Providers", "Provider status", "Show saved provider credentials without revealing secrets.", prompt="/provider"),
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


def _search_key(value: str) -> str:
    """Normalize searches so accents and capitalization do not matter."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))



from isycode.terminal_safety import install as _install_terminal_safety

_install_terminal_safety()

class CommandBrowser(App[None]):
    """Navigate available actions as semantic folders rather than shell flags."""

    TITLE = "ISyCode · Commands"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #111116; }
    #cli-header { dock: top; height: 3; padding: 1 2; background: #201e26; color: #bb8cff; text-style: bold; }
    #cli-body { height: 1fr; padding: 1 2; }
    #command-navigation { width: 42; min-width: 30; height: 1fr; }
    #command-search { height: 3; margin-bottom: 1; }
    #command-tree { width: 1fr; height: 1fr; border: round #383541; background: #17161d; padding: 1; }
    #selection-panel { width: 1fr; height: 1fr; margin-left: 1; padding: 1 2; border: round #383541; background: #17161d; }
    #selection-title { height: 2; color: #bb8cff; text-style: bold; }
    #selection-path { height: 2; color: #aaa7b8; }
    #selection-description { height: 1fr; color: #e6e3ee; }
    #open-selection { width: 24; height: 3; dock: bottom; }
    Footer { background: #111116; color: #85849a; }
    """
    BINDINGS = [
        ("ctrl+o", "open_selected", "Open action"),
        ("q", "quit", "Quit"),
        ("escape", "back", "Clear / back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_action: CLIAction | None = None

    def compose(self) -> ComposeResult:
        yield Static("ISyCode  ·  COMMAND BROWSER", id="cli-header")
        with Horizontal(id="cli-body"):
            with Vertical(id="command-navigation"):
                yield Input(placeholder="Search commands…", id="command-search")
                yield Tree("Categories", id="command-tree")
            with Vertical(id="selection-panel"):
                yield Static("Choose an action", id="selection-title")
                yield Static("Agent · Workspace · Integrations · Providers · Session · Settings", id="selection-path")
                yield Static(
                    "Type to filter; press Tab to move to the list. Use ↑/↓ and Enter to inspect an action. "
                    "Ctrl+O opens it; Esc clears the filter or goes back. In chat, type / for quick commands.",
                    id="selection-description",
                )
                yield Button("Open action · Ctrl+O", id="open-selection", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_tree()
        self.query_one("#command-search", Input).focus()

    def _rebuild_tree(self, query: str = "") -> None:
        tree = self.query_one("#command-tree", Tree)
        tree.root.remove_children()
        tree.show_root = False
        match_count = 0
        normalized_query = _search_key(query)
        for category, actions in COMMAND_BRANCHES:
            matching = tuple(
                action for action in actions
                if not normalized_query or normalized_query in _search_key(" ".join((
                    action.category, action.name, action.description,
                )))
            )
            if not matching:
                continue
            match_count += len(matching)
            branch = tree.root.add(f"📁 {category}")
            for action in matching:
                branch.add_leaf(f"›  {action.name}", data=action)
            branch.expand()
        tree.root.expand()
        self.selected_action = None
        self.query_one("#open-selection", Button).disabled = True
        title = self.query_one("#selection-title", Static)
        path = self.query_one("#selection-path", Static)
        description = self.query_one("#selection-description", Static)
        if not query:
            title.update("Choose an action")
            path.update("Agent · Workspace · Integrations · Providers · Session · Settings")
            description.update(
                "Type to filter; press Tab to move to the list. Use ↑/↓ and Enter to inspect an action. "
                "Ctrl+O opens it; Esc clears the filter or goes back. In chat, type / for quick commands.")
        elif match_count:
            title.update(f"{match_count} {'result' if match_count == 1 else 'results'}")
            path.update(f'Matches for “{query}”')
            description.update("Choose a command from the list to inspect and open it.")
        else:
            title.update("No results")
            path.update(f'No matches for “{query}”')
            description.update("Try another term, or clear the search to see all commands.")

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
        search = self.query_one("#command-search", Input)
        if search.value:
            search.value = ""
            search.focus()
        else:
            self.exit()

    async def action_open_selected(self) -> None:
        if self.selected_action is None:
            self.notify("Select an action from the list first.", severity="warning")
            return
        self._open_selected()

    def _open_selected(self) -> None:
        if self.selected_action is not None:
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
            self._open_selected()


def main(argv: list[str] | None = None) -> None:
    """Run the semantic command browser for ``isycode cli``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["cli"]:
        print("Usage: isycode cli")
        return

    browser = CommandBrowser()
    browser.run()
    if browser.selected_action is None:
        return

    # Import only after the user opens an action, keeping startup lightweight.
    from isycode.tui import TUIApp

    action = browser.selected_action
    TUIApp(initial_view=action.view, initial_prompt=action.prompt).run()
