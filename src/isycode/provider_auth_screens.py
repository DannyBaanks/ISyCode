"""Login challenge UI: process-only, never appended to conversation history."""
import asyncio
from urllib.parse import urlsplit

from isycode.localization import tr
from isycode.provider_auth import ANTIGRAVITY_AUTH_HOSTS, AUTH_HOSTS
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


def _approved_login_url(value: object, *, allowed_hosts: tuple[str, ...] | None = None) -> str | None:
    """Return only official HTTPS sign-in URLs suitable for browser opening."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    hosts = allowed_hosts if allowed_hosts is not None else AUTH_HOSTS
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname not in hosts
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
        self.challenge = challenge
        self.provider = challenge.get('provider', 'chatgpt')
        self.slot = challenge.get('slot') or 'primary'
        allowed_hosts = (ANTIGRAVITY_AUTH_HOSTS[0],) if self.provider == 'antigravity' else AUTH_HOSTS
        self.login_url = _approved_login_url(challenge.get('url'), allowed_hosts=allowed_hosts)
        self.ready = asyncio.Event()
    def compose(self) -> ComposeResult:
        base_title = tr('Sign in with Google Antigravity') if self.provider == 'antigravity' else tr('Sign in with ChatGPT')
        title = f'{base_title} [{self.slot}]' if self.slot and self.slot != 'primary' else base_title
        with Vertical(id='subscription-card', classes='isy-dialog'):
            yield Static(title, classes='isy-dialog-title', markup=False)
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


class AccountSlotScreen(ModalScreen[str | None]):
    """Prompt for a new isolated subscription slot name (e.g. pro2, work)."""

    CSS = '''
    AccountSlotScreen { align: center middle; background: #000000 65%; }
    #account-slot-card { width: 68; max-width: 94%; height: auto; min-height: 10; padding: 1 2; border: solid #718291; background: #000000; }
    #account-slot-heading { height: 1; color: #edf1f5; text-style: bold; }
    #account-slot-note { height: auto; color: #9eaab6; margin-bottom: 1; }
    #account-slot-input { height: 3; margin-bottom: 1; }
    #account-slot-actions { height: 3; align-horizontal: right; }
    #account-slot-actions Button { margin-left: 1; }
    '''
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    def __init__(self, provider_label: str, suggested: str = 'pro2') -> None:
        super().__init__()
        self.provider_label = provider_label
        self.suggested = suggested

    def compose(self) -> ComposeResult:
        with Vertical(id='account-slot-card', classes='isy-dialog'):
            yield Static(tr('Add account slot · {provider}', provider=self.provider_label),
                         id='account-slot-heading', classes='isy-dialog-title', markup=False)
            yield Static(tr('Short label (letters, digits, - or _). Credentials stay isolated in this slot.'),
                         id='account-slot-note', markup=False)
            yield Input(value=self.suggested, placeholder='pro2', id='account-slot-input')
            with Horizontal(id='account-slot-actions', classes='isy-dialog-actions'):
                yield Button(tr('Cancel'), id='account-slot-cancel')
                yield Button(tr('Add & sign in'), id='account-slot-save', variant='primary')

    def on_mount(self) -> None:
        field = self.query_one('#account-slot-input', Input)
        field.focus()
        field.cursor_position = len(field.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == 'account-slot-save':
            self.dismiss(self.query_one('#account-slot-input', Input).value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'account-slot-input':
            self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
