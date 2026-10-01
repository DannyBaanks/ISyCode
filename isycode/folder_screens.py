"""Native user-only controls for sibling folders and delegated file-edit approval."""
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static


class AddWorkspaceFolderScreen(ModalScreen[dict | None]):
    CSS = """
    AddWorkspaceFolderScreen { align: center middle; background: #000000 65%; }
    #folder-card { width: 90; max-width: 96%; height: 90%; max-height: 95%; padding: 1 2; border: round #68696f; background: #292a2e; }
    #folder-card Static { height: auto; }
    #folder-card Input { height: 3; }
    #folder-actions { height: 3; dock: bottom; }
    #folder-content { height: 1fr; }
    #folder-actions Button { width: 1fr; }
    """
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, main: Path):
        super().__init__()
        self.main = main

    def compose(self) -> ComposeResult:
        with Vertical(id='folder-card'):
            with VerticalScroll(id='folder-content'):
                yield Static('Add sibling folder', markup=False)
                yield Static(f'Choose one real project folder directly inside {self.main.parent}', markup=False)
                yield Input(placeholder='Alias, e.g. other-project', id='folder-alias')
                yield Input(placeholder='Absolute folder path (spaces are supported)', id='folder-path')
                yield Checkbox('Allow proposed file edits', value=True, id='folder-editable')
                yield Static('This grants reads/searches and optionally edits for this exact folder. '
                             'Every edit asks until you explicitly enable automatic edits. '
                             'Commands and other projects receive no new access.', markup=False)
            with Horizontal(id='folder-actions'):
                yield Button('Cancel', id='folder-cancel')
                yield Button('Add folder', id='folder-add', variant='primary')

    def on_mount(self) -> None:
        self.query_one('#folder-alias', Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == 'folder-add':
            self.dismiss({'alias': self.query_one('#folder-alias', Input).value.strip(),
                          'path': self.query_one('#folder-path', Input).value.strip(),
                          'editable': self.query_one('#folder-editable', Checkbox).value})
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AutomaticEditsWarningScreen(ModalScreen[bool]):
    CSS = """
    AutomaticEditsWarningScreen { align: center middle; background: #000000 65%; }
    #auto-edit-card { width: 90; max-width: 96%; height: 90%; max-height: 95%; padding: 1 2; border: round #f87171; background: #292a2e; }
    #auto-edit-card Static { height: auto; margin-bottom: 1; }
    #auto-edit-actions { height: 3; dock: bottom; }
    #auto-edit-content { height: 1fr; }
    #auto-edit-actions Button { width: 1fr; }
    """
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, root: Path):
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id='auto-edit-card'):
            with VerticalScroll(id='auto-edit-content'):
                yield Static('Danger: allow automatic file edits', markup=False)
                yield Static(f'Folder: {self.root}', markup=False)
                yield Static('The assistant may create or overwrite files here without showing '
                             'each diff for approval. Model mistakes or malicious instructions in '
                             'files can damage your work. Review changes with Git and keep backups.', markup=False)
                yield Static('This setting persists for this workspace. Disable it from Files → Folders. '
                             'Authority, ISySentinel, path protections and journaling stay active; '
                             'they cannot guarantee that an allowed edit is correct. Commands, deletes, '
                             'moves and commits still require their own approvals.', markup=False)
            with Horizontal(id='auto-edit-actions'):
                yield Button('Cancel', id='auto-edit-cancel')
                yield Button('Enable automatic edits', id='auto-edit-enable', variant='error')

    def on_mount(self) -> None:
        self.query_one('#auto-edit-cancel', Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == 'auto-edit-enable')

    def action_cancel(self) -> None:
        self.dismiss(False)
