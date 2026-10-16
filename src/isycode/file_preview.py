from pathlib import Path
from textual.app import ComposeResult
from isycode.localization import tr
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea
from isycode.tui_copy import CopyTextArea
from isycode.tui_screens_approval import DECISION_CSS


def guess_syntax_language(path: str | Path | None) -> str | None:
    """Map file extension to Textual's supported tree-sitter syntax languages."""
    if not path:
        return None
    ext = Path(path).suffix.lower()
    mapping = {
        ".py": "python",
        ".pyi": "python",
        ".json": "json",
        ".md": "markdown",
        ".markdown": "markdown",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "javascript",
        ".tsx": "javascript",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".rs": "rust",
        ".go": "go",
        ".sql": "sql",
        ".xml": "xml",
        ".java": "java",
    }
    return mapping.get(ext)


class FilePreviewScreen(ModalScreen[None]):
    CSS = DECISION_CSS + '''
    FilePreviewScreen { align: center middle; background: #000000 58%; }
    #preview-card { width: 110; }
    #preview-heading { height: auto; max-height: 4; }
    #preview-text { height: 1fr; background: #000000; border: none; }
    #preview-text .text-area--gutter { background: #000000; color: #718291; }
    #preview-text .text-area--selection { background: #002c36; }
    '''
    BINDINGS = [Binding('escape','close','Close')]
    def __init__(self,path,text):
        super().__init__();self.path=path;self.text=text
    def compose(self) -> ComposeResult:
        lang = guess_syntax_language(self.path)
        with Vertical(id='preview-card', classes='isy-dialog'):
            yield Static(str(self.path),id='preview-heading',classes='isy-dialog-title',markup=False)
            yield CopyTextArea(
                self.text,
                language=lang,
                theme="monokai",
                read_only=True,
                id='preview-text',
                show_line_numbers=True,
            )
            with Horizontal(id='preview-actions', classes='isy-dialog-actions'):
                yield Button(tr('Copy selection'),id='preview-copy',disabled=True)
                yield Button(tr('Copy whole box'),id='preview-copy-whole')
                yield Button(tr('Close'),id='preview-close')
            yield Static(tr('Read-only · select with mouse or Ctrl+A; Ctrl+C copies'),
                         classes='isy-dialog-hint',markup=False)
    def on_text_area_selection_changed(self,event):
        self.query_one('#preview-copy',Button).disabled=not event.text_area.selected_text
    def on_mount(self):self.query_one(TextArea).focus()
    async def on_button_pressed(self,event):
        event.stop()
        if event.button.id=='preview-copy':
            editor=self.query_one(TextArea)
            if editor.selected_text:
                self.app.run_worker(self.app._request_clipboard_copy(editor.selected_text,'selection'), group='clipboard-user')
        elif event.button.id=='preview-copy-whole':
            self.app.run_worker(self.app._request_clipboard_copy(self.text,'content_box'),group='clipboard-user')
        else:self.dismiss(None)
    def action_close(self):self.dismiss(None)
