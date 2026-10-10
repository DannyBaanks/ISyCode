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
    #child-card { width: 95; max-width: 96%; height: 85%; padding: 1 1; border: round #514d5a; background: #17191f; }
    #child-task { height: 2; }
    #child-copy { height: auto; max-height: 3; }
    #child-search { height: 3; margin: 1 0; }
    #child-models { height: 1fr; }
    .child-group { height: auto; background: transparent; }
    .child-model-choice { width: 100%; height: auto; min-height: 1; border: none; background: transparent; padding: 0 1; margin: 0; text-align: left; }
    .child-model-choice:focus, .child-model-choice:hover { background: #30303c; }
    #child-selected { height: auto; margin: 1 0; color: #77d8b0; }
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
        with Vertical(id='child-card'):
            yield Static(tr('Subagent · select a model from your providers'),markup=False)
            if self.error:
                yield Static(Text(self.error["provider_hint"] + "\nChoose another model or Cancel. Completed effects remain; retry may repeat work.", style="#e9c778"), id="child-error")
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
                    with ExpandableBox(title=f"{PRESETS.get(provider, {}).get('label', provider)} · {len(items)} models",
                                       collapsed=True, classes='child-group'):
                        for index, item in items:
                            label = Text(model_display_name(item['model']), style='#e0e0e0')
                            label.append(' / ' + item['model'], style='#9aa3ad')
                            yield Button(label, id=f'child-choice-{index}', classes='child-model-choice')
            yield Static(self._selected_label(), id='child-selected', markup=False)
            with Horizontal(id='child-buttons'):
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
            self.query_one('#child-selected', Static).update(self._selected_label())
        else:
            self.dismiss(None)

    def _selected_label(self):
        if self.selected is None:
            return 'No models available.'
        from isycode.providers import PRESETS
        from isycode.model_presentation import model_display_name
        item = self.selected
        provider = PRESETS.get(item['provider'], {}).get('label', item['provider'])
        return f"Selected · {model_display_name(item['model'])} · {provider}"

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
