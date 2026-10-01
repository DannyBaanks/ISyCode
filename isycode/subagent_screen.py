"""Explicit model selection for every child launch; no preference mutation."""
import asyncio
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Button, OptionList
from textual.widgets.option_list import Option

class SubagentModelScreen(ModalScreen[dict | None]):
    CSS = '''
    SubagentModelScreen { align: center middle; background: #000000 65%; }
    #child-card { width: 95; max-width: 96%; height: 95%; padding: 1 1; border: round #68696f; background: #292a2e; }
    #child-task { height: 2; }
    #child-copy { height: auto; max-height: 3; }
    #child-models { height: 1fr; }
    #child-buttons { height: 3; dock: bottom; }
    #child-buttons Button { width: 1fr; min-width: 0; }
    '''
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]
    def __init__(self, task: str, models: list[dict]):
        super().__init__();self.ready=asyncio.Event();self.assigned_task=task;self.models=[dict(item) for item in models]
    def compose(self) -> ComposeResult:
        with Vertical(id='child-card'):
            yield Static('Subagent · select a recent model',markup=False)
            with VerticalScroll(id='child-task'):
                yield Static(self.assigned_task,markup=False)
            yield Static('Assigned task and requested files go to this provider. File edits use current grants and approvals. The parent waits; Cancel sends nothing.',id='child-copy',markup=False)
            yield OptionList(*(Option(Text(f"{item['provider']} · {item['model']}")) for item in self.models),id='child-models')
            with Horizontal(id='child-buttons'):
                yield Button('Cancel',id='child-cancel')
                yield Button('Launch selected model',id='child-launch',disabled=not self.models,variant='primary')
    def on_mount(self):
        self.query_one('#child-models',OptionList).highlighted=0 if self.models else None
        self.query_one('#child-cancel',Button).focus()
        self.ready.set()
    def on_button_pressed(self,event:Button.Pressed):
        event.stop()
        if event.button.id=='child-launch':
            index=self.query_one('#child-models',OptionList).highlighted
            if index is not None and 0<=index<len(self.models):self.dismiss(dict(self.models[index]))
        else:self.dismiss(None)
    def action_cancel(self):self.dismiss(None)
