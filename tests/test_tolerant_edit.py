"""workspace_edit finds a fragment despite whitespace drift, never by guessing."""
import os
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import EDIT_TOOL, WorkspaceWriteOwner, tolerant_replace

pytestmark = pytest.mark.skipif(os.name == "nt", reason="descriptor-safe writes are POSIX-only")

SOURCE = (
    "class Parser:\n"
    "    def parse(self, text):\n"
    "        if not text:\n"
    "            return None\n"
    "        return text.split()\n"
)


# ── The matcher ────────────────────────────────────────────────────────
def test_exact_text_never_reaches_the_tolerant_matcher(tmp_path, monkeypatch):
    owner, approvals, root = make_owner(tmp_path, monkeypatch, SOURCE)
    preview = owner.preview_edit("app.py", "return None", "return []")
    assert preview.match == "exact"


def test_indentation_drift_is_matched_and_new_text_is_reindented():
    model_wrote = "if not text:\n    return None"                  # dedented by 8
    updated, stage = tolerant_replace(SOURCE, model_wrote, "if not text:\n    return []\n# empty")
    assert stage == "indentation"
    assert updated == SOURCE.replace(
        "        if not text:\n            return None\n",
        "        if not text:\n            return []\n        # empty\n")


def test_tabs_versus_spaces_is_indentation_drift():
    updated, stage = tolerant_replace(SOURCE, "\tif not text:\n\t\treturn None",
                                      "\tif not text:\n\t\treturn 0")
    assert stage == "indentation" and "            return 0\n" in updated


def test_trailing_whitespace_and_line_endings_are_ignored_and_the_file_style_kept():
    crlf = "a = 1   \r\nb = 2\r\n"
    updated, stage = tolerant_replace(crlf, "a = 1\nb = 2", "a = 10\nb = 20")
    assert stage == "trailing-whitespace" and updated == "a = 10\r\nb = 20\r\n"
    updated, stage = tolerant_replace("x\r\ny\r\n", "x\ny", "z")
    assert stage == "line-endings" and updated == "z\r\n"


def test_an_ambiguous_loose_match_is_refused_not_guessed():
    twice = "def a():\n    pass\n\nclass B:\n        pass\n"
    with pytest.raises(ValueError, match="matches 2 places when ignoring indentation"):
        tolerant_replace(twice, "pass", "return 1")


def test_a_fragment_inside_a_line_never_matches_loosely():
    with pytest.raises(ValueError, match="not found"):
        tolerant_replace(SOURCE, "return   text", "return text")
    with pytest.raises(ValueError, match="not found"):
        tolerant_replace(SOURCE, "   \n  ", "x")                     # blank old_text


def test_a_file_with_mixed_line_endings_only_accepts_exact_text():
    mixed = "a = 1\r\nb = 2\nc = 3\r\n"
    with pytest.raises(ValueError, match="mixes CRLF and LF"):
        tolerant_replace(mixed, "b = 2  ", "b = 20")


# ── Through the owner: still the exact diff, still an approval ─────────
def make_owner(tmp_path: Path, monkeypatch, content: str):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text(content, encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root.resolve()])
    approvals = ActionApprovalStore()
    return WorkspaceWriteOwner(root, authority, approvals), approvals, root


def test_a_loose_match_is_previewed_as_the_exact_diff_and_needs_the_same_approval(tmp_path, monkeypatch):
    owner, approvals, root = make_owner(tmp_path, monkeypatch, SOURCE)
    preview = owner.preview_edit("app.py", "if not text:\n    return None",
                                 "if not text:\n    return []")
    assert preview.match == "indentation"
    assert "-            return None" in preview.diff
    assert "+            return []" in preview.diff
    assert (root / "app.py").read_text() == SOURCE                  # nothing written by preview
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW", outcome.reason
    assert (root / "app.py").read_text() == SOURCE.replace("return None", "return []")


def test_the_tool_description_tells_the_model_how_matching_works():
    text = EDIT_TOOL["function"]["description"]
    assert "indentation" in text and "unique" in text and "exact diff" in text


@pytest.mark.parametrize("source, old, new, expected", [
    # model indents by 2, file by 4: a deeper new line follows the file's unit
    ("def f():\n    if a:\n        b()\n", "if a:\n  b()", "if a:\n  if c:\n    b()",
     "def f():\n    if a:\n        if c:\n            b()\n"),
    # model uses spaces, file uses tabs: no space lands in the tab file
    ("def f():\n\tif a:\n\t\tb()\n", "if a:\n    b()", "if a:\n    if c:\n        b()",
     "def f():\n\tif a:\n\t\tif c:\n\t\t\tb()\n"),
])
def test_new_lines_follow_the_files_indentation_unit(source, old, new, expected):
    assert tolerant_replace(source, old, new) == (expected, "indentation")


def test_the_chat_shows_how_the_edit_was_matched_and_tells_the_model(tmp_path, monkeypatch, capsys):
    import asyncio
    import json
    from test_daily_tui import configure
    from isycode.tui import TUIApp, WriteApprovalScreen, plain_text
    from textual.widgets import Static
    root = configure(tmp_path, monkeypatch)
    (root / "app.py").write_text(SOURCE)
    seen = []

    async def complete(provider, messages, **kwargs):
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            return {"text": "", "tool_calls": [{"id": "e1", "type": "function", "function": {
                "name": "workspace_edit", "arguments": json.dumps({
                    "path": "app.py", "old_text": "if not text:\n    return None",
                    "new_text": "if not text:\n    return []"})}}]}
        return {"text": "Done.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat("Return an empty list"))
            reviewed = False
            for _ in range(80):
                await pilot.pause(0.05)
                if isinstance(app.screen, WriteApprovalScreen) and not reviewed:
                    reviewed = True                     # the same approval as an exact edit
                    await pilot.press("tab", "enter")
                if task.done():
                    break
            await asyncio.wait_for(task, timeout=5)
            assert reviewed
            assert (root / "app.py").read_text() == SOURCE.replace("return None", "return []")
            result = json.loads([m for m in seen[-1] if m["role"] == "tool"][0]["content"])
            assert result["status"] == "written" and result["matched_ignoring"] == "indentation"
            shown = " ".join(plain_text(item) for item in app.query(Static))
            assert "matched ignoring indentation" in shown

    with capsys.disabled():
        asyncio.run(scenario())
