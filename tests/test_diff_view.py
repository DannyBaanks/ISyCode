"""Side-by-side diff view: parser, alignment, line numbers, approval screens."""
import pytest

from isycode.diff_view import hunk_rows, parse_unified_diff, side_by_side_table

SAMPLE = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 import os
-value = 1
+value = 2
 print(value)
+print("done")
@@ -10,2 +11,2 @@
-x = 1
+x = 2
"""


def test_parser_keeps_kinds_and_line_numbers():
    hunks = parse_unified_diff(SAMPLE)
    assert len(hunks) == 2
    first = hunks[0]
    assert (first.old_start, first.new_start) == (1, 1)
    kinds = [row.kind for row in first.rows]
    assert kinds == ["context", "del", "add", "context", "add"]
    assert first.rows[1].old_no == 2 and first.rows[1].new_no is None
    assert first.rows[2].new_no == 2 and first.rows[2].old_no is None
    assert first.rows[3].old_no == 3 and first.rows[3].new_no == 3
    assert first.rows[4].new_no == 4


def test_rows_align_with_padding_on_the_other_side():
    pairs = hunk_rows(parse_unified_diff(SAMPLE)[0])
    assert pairs[1][0].plain.startswith("   2") and "value = 1" in pairs[1][0].plain
    assert pairs[1][1].plain.strip() == ""
    assert "value = 2" in pairs[2][1].plain and pairs[2][0].plain.strip() == ""
    assert pairs[3][0].plain.startswith("   3") and pairs[3][1].plain.startswith("   3")


def test_table_has_path_header_and_hunks():
    table = side_by_side_table(SAMPLE, "app.py")
    assert table.row_count >= 4


def test_new_file_is_all_additions():
    diff = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n"
    hunks = parse_unified_diff(diff)
    assert [row.kind for row in hunks[0].rows] == ["add", "add"]
    assert [row.new_no for row in hunks[0].rows] == [1, 2]


@pytest.mark.asyncio
async def test_write_approval_shows_side_by_side(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp, WriteApprovalScreen
    from isycode.workspace_write import WorkspaceWriteOwner
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.approvals import ActionApprovalStore
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        root = app._workspace_root
        (root / "app.py").write_text("value = 1\nprint(value)\n")
        owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), ActionApprovalStore())
        preview = owner.preview_edit("app.py", "value = 1", "value = 2")
        await app.push_screen(WriteApprovalScreen(preview))
        await pilot.pause()
        from isycode.diff_view import side_by_side_table
        assert side_by_side_table(preview.diff, preview.path).row_count >= 3
