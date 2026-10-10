"""Native user-only controls for sibling folders and delegated file-edit approval."""
from pathlib import Path
from isycode.localization import tr

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static


class AddWorkspaceFolderScreen(ModalScreen[dict | None]):
    CSS = """
    AddWorkspaceFolderScreen { align: center middle; background: #000000 58%; }
    #folder-card { width: 90; max-width: 96%; height: 90%; max-height: 95%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #folder-card Static { height: auto; }
    #folder-card Input { height: 3; }
    #folder-actions { height: 3; dock: bottom; align-horizontal: right; }
    #folder-content { height: 1fr; }
    #folder-actions Button { width: auto; min-width: 18; margin-left: 1; }
    """
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, main: Path, selected_folder: Path):
        super().__init__()
        self.main = main
        self.selected_folder = selected_folder

    def compose(self) -> ComposeResult:
        with Vertical(id='folder-card'):
            with VerticalScroll(id='folder-content'):
                yield Static(tr('Add sibling folder'), markup=False)
                yield Static(f'Selected sibling folder: {self.selected_folder}', markup=False)
                yield Input(placeholder=tr('Alias, e.g. other-project'), id='folder-alias')
                yield Checkbox(tr('Allow proposed file edits'), value=True, id='folder-editable')
                yield Static(tr('This grants reads/searches and optionally edits for this exact folder. '
                             'Every edit asks until you explicitly enable automatic edits. '
                             'Commands and other projects receive no new access.'), markup=False)
            with Horizontal(id='folder-actions'):
                yield Button(tr('Cancel'), id='folder-cancel')
                yield Button(tr('Add folder'), id='folder-add', variant='primary')

    def on_mount(self) -> None:
        self.query_one('#folder-alias', Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == 'folder-add':
            self.dismiss({'alias': self.query_one('#folder-alias', Input).value.strip(),
                          'path': str(self.selected_folder),
                          'editable': self.query_one('#folder-editable', Checkbox).value})
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AutomaticEditsWarningScreen(ModalScreen[bool]):
    CSS = """
    AutomaticEditsWarningScreen { align: center middle; background: #000000 58%; }
    #auto-edit-card { width: 90; max-width: 96%; height: 90%; max-height: 95%; padding: 1 2; border: round #f87171; background: #292a2e; }
    #auto-edit-card Static { height: auto; margin-bottom: 1; }
    #auto-edit-actions { height: 3; dock: bottom; align-horizontal: right; }
    #auto-edit-content { height: 1fr; }
    #auto-edit-actions Button { width: auto; min-width: 18; margin-left: 1; }
    """
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, root: Path):
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id='auto-edit-card'):
            with VerticalScroll(id='auto-edit-content'):
                yield Static(tr('Danger: allow automatic file edits'), markup=False)
                yield Static(f'Folder: {self.root}', markup=False)
                yield Static(tr('The assistant may create or overwrite files here without showing '
                             'each diff for approval. Model mistakes or malicious instructions in '
                             'files can damage your work. Review changes with Git and keep backups.'), markup=False)
                yield Static(tr('This setting persists for this workspace. Disable it from Files → Folders. '
                             'Authority, ISySentinel, path protections and journaling stay active; '
                             'they cannot guarantee that an allowed edit is correct. Commands, deletes, '
                             'moves and commits still require their own approvals.'), markup=False)
            with Horizontal(id='auto-edit-actions'):
                yield Button(tr('Cancel'), id='auto-edit-cancel')
                yield Button(tr('Enable automatic edits'), id='auto-edit-enable', variant='error')

    def on_mount(self) -> None:
        self.query_one('#auto-edit-cancel', Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == 'auto-edit-enable')

    def action_cancel(self) -> None:
        self.dismiss(False)
