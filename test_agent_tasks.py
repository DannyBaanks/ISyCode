"""The agent's visible task list: validated, rendered, shown in the TUI, never an action."""
import ast
import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Static

from isycode.actions import ACTION_BY_ID
from isycode.agent_tasks import MAX_TASKS, TASK_TOOL_NAME, render_tasks, validate_tasks


def test_tasks_are_cleaned_to_single_printable_lines():
    tasks = validate_tasks({"tasks": [
        {"title": "  Read\nthe\x1b[2J code ", "status": "completed"},
        {"title": "Fix it", "status": "in_progress"},
        {"title": "Test", "status": "pending"},
    ]})
    assert tasks[0]["title"] == "Read the[2J code"
    text = render_tasks(tasks).plain
    assert text.startswith("Tasks · 1/3 done") and "▶ Fix it" in text and "○ Test" in text


@pytest.mark.parametrize("arguments", [
    None, {}, {"tasks": "x"}, {"tasks": [{"title": "", "status": "pending"}]},
    {"tasks": [{"title": "a", "status": "done"}]},
    {"tasks": [{"title": "a", "status": "pending"}] * (MAX_TASKS + 1)},
])
def test_invalid_task_lists_are_rejected(arguments):
    with pytest.raises(ValueError):
        validate_tasks(arguments)


def test_the_task_list_is_not_a_catalog_action():
    assert not any("task" in action for action in ACTION_BY_ID)


def test_panel_shows_and_hides_with_the_list():
    from isycode.tui import TUIApp

    class Host(App):
        _show_agent_tasks = TUIApp._show_agent_tasks

        def compose(self):
            yield Static("", id="agent-tasks")

    async def scenario():
        async with Host().run_test() as pilot:
            app = pilot.app
            panel = app.query_one("#agent-tasks", Static)
            app._show_agent_tasks(validate_tasks({"tasks": [{"title": "Plan", "status": "in_progress"}]}))
            await pilot.pause()
            shown = panel.display
            app._show_agent_tasks([])
            await pilot.pause()
            return shown, panel.display

    assert asyncio.run(scenario()) == (True, False)


def test_chat_routes_the_task_tool_without_any_owner():
    source = (Path(__file__).parent / "isycode" / "tui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    dispatch = ast.get_source_segment(source, next(
        node for node in app.body if getattr(node, "name", "") == "_dispatch_chat_tool"))
    branch = dispatch[dispatch.index("if name == TASK_TOOL_NAME"):]
    branch = branch[:branch.index("action_id = TOOL_ACTIONS[name]")]
    assert "validate_tasks(arguments)" in branch and "Owner" not in branch
    assert TASK_TOOL_NAME == "update_tasks"
