"""Selectable read-only file preview; all copying remains behind ClipboardOwner."""
from textual.app import ComposeResult
from isycode.localization import tr
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

class FilePreviewScreen(ModalScreen[None]):
    CSS = '''
    FilePreviewScreen { align: center middle; background: #000000 58%; }
    #preview-card { width: 110; max-width: 96%; height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #preview-heading { height: auto; max-height: 4; }
    #preview-text { height: 1fr; }
    #preview-actions { height: 3; dock: bottom; align-horizontal: right; }
    #preview-actions Button { width: auto; min-width: 18; margin-left: 1; }
    '''
    BINDINGS = [Binding('escape','close','Close')]
    def __init__(self,path,text):
        super().__init__();self.path=path;self.text=text
    def compose(self) -> ComposeResult:
        with Vertical(id='preview-card'):
            yield Static(f'{self.path}\nRead-only · select with mouse or Ctrl+A; Ctrl+C copies',id='preview-heading',markup=False)
            yield TextArea(self.text,read_only=True,id='preview-text',show_line_numbers=True)
            with Horizontal(id='preview-actions'):
                yield Button(tr('Copy selection / text'),id='preview-copy')
                yield Button(tr('Close'),id='preview-close')
    def on_mount(self):self.query_one(TextArea).focus()
    async def on_button_pressed(self,event):
        event.stop()
        if event.button.id=='preview-copy':
            editor=self.query_one(TextArea)
            self.app.run_worker(self.app._request_clipboard_copy(editor.selected_text or self.text,'selection'), group='clipboard-user')
        else:self.dismiss(None)
    def action_close(self):self.dismiss(None)
