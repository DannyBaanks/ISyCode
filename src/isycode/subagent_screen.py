"""Explicit model selection for every child launch; no preference mutation."""
import asyncio
from isycode.localization import tr
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input

class SubagentModelScreen(ModalScreen[dict | None]):
    CSS = '''
    SubagentModelScreen { align: center middle; background: #000000 58%; }
    #child-card { width: 95; max-width: 96%; height: 92%; padding: 0 1; border: solid #718291; background: #000000; }
    #child-heading { height: 1; text-style: bold; color: #edf1f5; }
    #child-task { height: 2; }
    #child-copy { height: auto; max-height: 2; color: #a9b5c2; }
    #child-search { height: 3; margin: 0; }
    #child-models { height: 1fr; min-height: 2; }
    .child-group { height: auto; background: transparent; }
    .child-model-choice { width: 100%; height: auto; min-height: 1; border: none; background: transparent; padding: 0 1; margin: 0; text-align: left; }
    .child-model-choice:focus, .child-model-choice:hover, .child-model-choice.-selected { background: #03252d; color: #38e1ee; }
    #child-selected { height: auto; max-height: 3; margin: 0; color: #a9b5c2; border-top: solid #3f4d59; }
    #child-buttons { height: 3; dock: bottom; align-horizontal: right; }
    #child-buttons Button { width: auto; min-width: 18; margin-left: 1; }
    '''
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]
    def __init__(self, task: str, models: list[dict], error: dict | None = None):
        super().__init__()
        self.error = error
        self.ready = asyncio.Event()
        self.assigned_task = task
        self.models = [dict(item) for item in models]
        self.selected = dict(self.models[0]) if self.models else None
    def compose(self) -> ComposeResult:
        with Vertical(id='child-card', classes='isy-dialog'):
            yield Static(tr('Subagent · select a model from your providers'), id='child-heading', classes='isy-dialog-title', markup=False)
            if self.error:
                yield Static(Text(tr("{provider_hint}\nChoose another model or Cancel. Completed effects remain; retry may repeat work.", provider_hint=self.error["provider_hint"]), style="#e9c778"), id="child-error")
            with VerticalScroll(id='child-task'):
                yield Static(self.assigned_task,markup=False)
            yield Static(tr('Assigned task and requested files go to this provider. File edits use current grants and approvals. The parent waits; Cancel sends nothing.'),id='child-copy',markup=False)
            yield Input(placeholder=tr('Find a model or provider…'), id='child-search')
            from isycode.tui import ExpandableBox
            from isycode.providers import PRESETS
            from isycode.model_presentation import model_display_name
            groups = {}
            for index, item in enumerate(self.models):
                groups.setdefault(item['provider'], []).append((index, item))
            with VerticalScroll(id='child-models'):
                for provider, items in groups.items():
                    with ExpandableBox(title=tr("{get} · {len} models", get=PRESETS.get(provider, {}).get('label', provider), len=len(items)),
                                       collapsed=True, classes='child-group'):
                        for index, item in items:
                            label = Text(model_display_name(item['model']), style='#edf1f5')
                            yield Button(label, id=f'child-choice-{index}', classes='child-model-choice')
            yield Static(self._selected_label(), id='child-selected', markup=False)
            with Horizontal(id='child-buttons', classes='isy-dialog-actions'):
                yield Button(tr('Cancel'),id='child-cancel')
                yield Button(tr('Launch selected model'),id='child-launch',disabled=not self.models,variant='primary')
    def on_mount(self):
        self.query_one('#child-cancel',Button).focus()
        self.ready.set()
    def on_button_pressed(self,event:Button.Pressed):
        event.stop()
        if event.button.id=='child-launch':
            if self.selected is not None:
                self.dismiss(dict(self.selected))
        elif event.button.id and event.button.id.startswith('child-choice-'):
            index = int(event.button.id.removeprefix('child-choice-'))
            self.selected = dict(self.models[index])
            for button in self.query('.child-model-choice'):
                button.set_class(button.id == event.button.id, '-selected')
            self.query_one('#child-selected', Static).update(self._selected_label())
        else:
            self.dismiss(None)

    def _selected_label(self):
        if self.selected is None:
            return tr('No models available.')
        from isycode.providers import PRESETS
        from isycode.model_presentation import model_display_name
        item = self.selected
        provider = PRESETS.get(item['provider'], {}).get('label', item['provider'])
        return tr('Selected · {model} · {provider}', model=model_display_name(item['model']), provider=provider) + '\n' + item['model']

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != 'child-search':
            return
        query = event.value.strip().casefold()
        from isycode.providers import PRESETS
        for group in self.query('.child-group'):
            matches = 0
            for button in group.query(Button):
                item = self.models[int(button.id.removeprefix('child-choice-'))]
                provider = PRESETS.get(item['provider'], {}).get('label', item['provider'])
                button.display = not query or query in f"{provider} {item['model']}".casefold()
                matches += bool(button.display)
            group.display = bool(matches)
            if query and matches:
                group.collapsed = False
    def action_cancel(self):self.dismiss(None)
