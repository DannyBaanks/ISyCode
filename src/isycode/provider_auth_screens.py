"""Login challenge UI: process-only, never appended to conversation history."""
import asyncio
from urllib.parse import urlsplit

from isycode.localization import tr
from isycode.provider_auth import AUTH_HOSTS
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


def _approved_login_url(value: object) -> str | None:
    """Return only official HTTPS sign-in URLs suitable for browser opening."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname not in AUTH_HOSTS
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or '\\' in value
                or any(char.isspace() for char in value)):
            return None
    except ValueError:
        return None
    return value


class SubscriptionLoginScreen(ModalScreen[None]):
    CSS = '''
    SubscriptionLoginScreen { align: center middle; background: #000000 65%; }
    #subscription-card { width: 90; max-width: 96%; height: 90%; padding: 0 1; border: solid #718291; background: #000000; }
    #subscription-copy { height: 1fr; }
    #subscription-copy Static { height: auto; margin-bottom: 1; }
    #subscription-actions { dock: bottom; height: 3; align-horizontal: right; }
    #subscription-actions Button { width: auto; min-width: 18; margin-left: 1; }
    #subscription-open-link { min-width: 28; }
    '''
    BINDINGS = [Binding('escape','cancel','Cancel')]
    def __init__(self, challenge):
        super().__init__()
        self.challenge=challenge
        self.login_url = _approved_login_url(challenge.get('url'))
        self.ready=asyncio.Event()
    def compose(self) -> ComposeResult:
        with Vertical(id='subscription-card', classes='isy-dialog'):
            yield Static(tr('Sign in with ChatGPT'), classes='isy-dialog-title', markup=False)
            with VerticalScroll(id='subscription-copy', classes='isy-dialog-body'):
                yield Static(tr('Open this official link in your browser. Browser login requires the browser on the same computer as ISyCode; use device code for remote/headless machines.'),markup=False)
                if self.login_url:
                    yield Static(self.login_url, id='subscription-url', markup=False)
                else:
                    yield Static(tr('Sign-in link failed safety validation; it will not be opened.'),
                                 id='subscription-url', markup=False)
                yield Static('', id='subscription-open-status', markup=False)
                if self.challenge.get('user_code'):
                    yield Static(tr('Enter this one-use code: ')+self.challenge['user_code'],markup=False)
                yield Static(tr('Waiting for sign-in… Your plan determines available models and usage limits. This does not add API credits.'),markup=False)
            with Horizontal(id='subscription-actions'):
                yield Button(tr('Open sign-in in browser'), id='subscription-open-link',
                             disabled=self.login_url is None)
                yield Button(tr('Cancel sign-in'),id='subscription-cancel')
    def on_mount(self):
        self.query_one('#subscription-cancel',Button).focus()
        self.ready.set()
    def on_button_pressed(self,event):
        event.stop()
        if event.button.id == 'subscription-open-link':
            if self.login_url:
                try:
                    self.app.open_url(self.login_url, new_tab=True)
                except Exception:
                    self.query_one('#subscription-open-status', Static).update(
                        tr('Could not open the browser. Copy the official URL and open it manually.'))
            return
        if event.button.id == 'subscription-cancel':
            self.dismiss(None)
    def action_cancel(self): self.dismiss(None)
