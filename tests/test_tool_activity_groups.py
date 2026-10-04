import asyncio
import json
from isycode.tui import TUIApp, ToolActivityGroup
from isycode.operation_style import operation_color
from test_daily_tui import configure


def test_consecutive_same_tools_group_as_tree_with_distinct_operation_colors(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def impl(self, call):
        return call["id"], json.dumps({"status": "ok"})
    monkeypatch.setattr(TUIApp, "_dispatch_chat_tool_impl", impl)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            for index, name in enumerate(("workspace_read", "workspace_read", "workspace_grep", "workspace_read")):
                await app._dispatch_chat_tool({"id": str(index), "function": {"name": name, "arguments": json.dumps({"path": f"file{index}.py"})}})
            await pilot.pause()
            groups = list(app.query(ToolActivityGroup))
            assert len(groups) == 3
            assert len(groups[0].leaves) == 2
            assert groups[0].leaves[0][0].title.startswith("├─ ")
            assert groups[0].leaves[1][0].title.startswith("└─ ")
            assert "Completed" in groups[0].leaves[0][0].title
            assert all(leaf._title.collapsed_symbol == "" and leaf._title.expanded_symbol == "" for leaf, _ in groups[0].leaves)
            for single in groups[1:]:
                leaf = single.leaves[0][0]
                assert not leaf._title.display
                assert not leaf.collapsed
                assert "└─" not in leaf.title
                single.collapsed = False
            assert "file1.py" in groups[0].leaves[1][0].title
            assert len({operation_color(n) for n in ("workspace_read", "workspace_grep", "workspace_run", "workspace_write")}) == 4
    asyncio.run(scenario())
