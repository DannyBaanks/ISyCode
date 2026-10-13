"""Login challenge UI: process-only, never appended to conversation history."""
import asyncio
from isycode.localization import tr
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

class SubscriptionLoginScreen(ModalScreen[None]):
    CSS = '''
    SubscriptionLoginScreen { align: center middle; background: #000000 65%; }
    #subscription-card { width: 90; max-width: 96%; height: 90%; padding: 0 1; border: solid #718291; background: #000000; }
    #subscription-copy { height: 1fr; }
    #subscription-copy Static { height: auto; margin-bottom: 1; }
    #subscription-cancel { dock: bottom; width: 100%; height: 3; }
    '''
    BINDINGS = [Binding('escape','cancel','Cancel')]
    def __init__(self, challenge):
        super().__init__()
        self.challenge=challenge
        self.ready=asyncio.Event()
    def compose(self) -> ComposeResult:
        with Vertical(id='subscription-card', classes='isy-dialog'):
            yield Static(tr('Sign in with ChatGPT'), classes='isy-dialog-title', markup=False)
            with VerticalScroll(id='subscription-copy', classes='isy-dialog-body'):
                yield Static(tr('Open this official link in your browser. Browser login requires the browser on the same computer as ISyCode; use device code for remote/headless machines.'),markup=False)
                yield Static(self.challenge['url'],markup=False)
                if self.challenge.get('user_code'):
                    yield Static(tr('Enter this one-use code: ')+self.challenge['user_code'],markup=False)
                yield Static(tr('Waiting for sign-in… Your plan determines available models and usage limits. This does not add API credits.'),markup=False)
            yield Button(tr('Cancel sign-in'),id='subscription-cancel')
    def on_mount(self):
        self.query_one('#subscription-cancel',Button).focus()
        self.ready.set()
    def on_button_pressed(self,event):
        event.stop();self.dismiss(None)
    def action_cancel(self): self.dismiss(None)
