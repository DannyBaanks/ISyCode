"""SVG/ASCII identity parity without fonts, credentials or network."""
import hashlib
import json
from pathlib import Path

import pytest

from core.file_icons import ascii_file_label, file_identity, TYPES, NAMES


@pytest.mark.parametrize("name,marker", [
    ("app.py", "[PY]"), ("APP.PYI", "[PY]"), ("main.js", "[JS]"),
    ("main.ts", "[TS]"), ("a.tsx", "[TSX]"), ("README.md", "[MD]"),
    ("config.yml", "[YAML]"), ("Dockerfile", "[DOCKER]"),
    (".gitignore", "[GIT]"), ("unknown.xyz", "[FILE]"),
    ("C:\\project\\app.py", "[PY]"),
])
def test_file_marker(name, marker):
    assert file_identity(name)[1] == marker
    assert marker.isascii()
    assert ascii_file_label(name) == marker + " " + name


def test_all_vendored_assets_match_receipts():
    root = Path(__file__).resolve().parents[1] / "ui/assets/vscode-icons"
    manifest = json.loads((root / "manifest.json").read_text())
    for record in manifest["files"]:
        assert hashlib.sha256((root / record["file"]).read_bytes()).hexdigest() == record["sha256"]
    for name in list(TYPES) + list(NAMES):
        key, _ = file_identity("a." + name if name in TYPES else name)
        assert (root / (key + ".svg")).is_file()
    assert file_identity("src", True) == ("default_folder", "[DIR]")


def test_native_file_icons_and_search(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from ui.panels.workspace import WorkspacePanel
    from ui.icons import file_icon
    (tmp_path / "app.py").write_text("print('hi')\n")
    panel = WorkspacePanel()
    qtbot.addWidget(panel)
    panel.set_root(tmp_path)
    source = panel.tree.model().sourceModel()
    index = source.index(str(tmp_path / "app.py"))
    qtbot.waitUntil(index.isValid)
    assert not source.data(index, Qt.ItemDataRole.DecorationRole).isNull()
    assert not file_icon("unknown").isNull()
    assert not file_icon("src", True).isNull()
    panel.search.setText("app")
    assert panel.results.count() == 1
    assert panel.results.item(0).text() == "app.py"
    assert not panel.results.item(0).icon().isNull()


def test_tui_proposal_uses_literal_ascii():
    import asyncio
    from types import SimpleNamespace
    from core.agent.chat import ChangeApprovalModal
    from textual.app import App
    from textual.widgets import Label
    call = SimpleNamespace(arguments={"path": "app.py"}, prepared_diff="sample", approval_kind="files")
    async def exercise():
        app = App()
        async with app.run_test(size=(100, 32)) as pilot:
            app.push_screen(ChangeApprovalModal(call))
            await pilot.pause()
            assert "[PY] app.py" in str(app.screen.query(Label).first().render())
    asyncio.run(exercise())


@pytest.mark.parametrize("chunk,expected", [
    ("\n✅ read: print('hello')", ("read", "print('hello')", True)),
    ("\r\n❌ edit: denied", ("edit", "denied", False)),
    ("Normal streamed response", None),
])
def test_actual_agent_tool_prefix_reaches_ascii_renderer(chunk, expected):
    from core.agent.chat import _parse_tool_chunk
    assert _parse_tool_chunk(chunk) == expected
