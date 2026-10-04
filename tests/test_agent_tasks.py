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
    assert text.startswith("▾ Tasks · 1/3 done") and "▶ Fix it" in text and "○ Test" in text


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
            app._tasks_collapsed = False
            panel = app.query_one("#agent-tasks", Static)
            app._show_agent_tasks(validate_tasks({"tasks": [{"title": "Plan", "status": "in_progress"}]}))
            await pilot.pause()
            shown = panel.display
            app._show_agent_tasks([])
            await pilot.pause()
            return shown, panel.display

    assert asyncio.run(scenario()) == (True, False)


def test_chat_routes_the_task_tool_without_any_owner():
    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    dispatch = None
    for path in (package / "tui.py", *sorted(package.glob("tui_app_*.py"))):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if getattr(item, "name", "") == "_dispatch_chat_tool_impl":
                    dispatch = ast.get_source_segment(source, item)
    assert dispatch is not None
    branch = dispatch[dispatch.index("if name == TASK_TOOL_NAME"):]
    branch = branch[:branch.index("action_id = TOOL_ACTIONS[name]")]
    assert "validate_tasks(arguments)" in branch and "Owner" not in branch
    assert TASK_TOOL_NAME == "update_tasks"


def test_a_finished_plan_collapses_to_one_line():
    tasks = validate_tasks({"tasks": [{"title": "A", "status": "completed"},
                                      {"title": "B", "status": "completed"}]})
    assert render_tasks(tasks).plain == "Tasks · 2/2 done ✓"


def test_the_panel_folds_to_one_line_with_the_current_step():
    tasks = validate_tasks({"tasks": [{"title": "Read", "status": "completed"},
                                      {"title": "Fix parser", "status": "in_progress"},
                                      {"title": "Test", "status": "pending"}]})
    folded = render_tasks(tasks, collapsed=True).plain
    assert "\n" not in folded and "1/3 done" in folded and "now: Fix parser" in folded
    assert "▾ Tasks" in render_tasks(tasks).plain


def test_click_and_ctrl_t_toggle_the_panel():
    from isycode.tui import TUIApp

    class Host(App):
        _show_agent_tasks = TUIApp._show_agent_tasks
        action_toggle_tasks = TUIApp.action_toggle_tasks
        BINDINGS = [("ctrl+t", "toggle_tasks")]

        def compose(self):
            from isycode.tui import TasksPanel
            yield TasksPanel("", id="agent-tasks")

    async def scenario():
        app = Host()
        app._agent_tasks, app._tasks_collapsed = [], False
        async with app.run_test() as pilot:
            app._show_agent_tasks(validate_tasks({"tasks": [
                {"title": "A", "status": "in_progress"}, {"title": "B", "status": "pending"}]}))
            await pilot.pause()
            states = [app._tasks_collapsed]
            await pilot.click("#agent-tasks")
            await pilot.pause()
            states.append(app._tasks_collapsed)
            await pilot.press("ctrl+t")
            await pilot.pause()
            states.append(app._tasks_collapsed)
            return states

    assert asyncio.run(scenario()) == [False, True, False]
