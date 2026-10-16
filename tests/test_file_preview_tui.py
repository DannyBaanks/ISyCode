import asyncio
from pathlib import Path
from isycode.tui import TUIApp
from test_daily_tui import configure

def test_file_leaf_enables_preview_modal_and_copy_path(tmp_path,monkeypatch,capsys):
    root=configure(tmp_path,monkeypatch);file=root/'hello.rs';file.write_text('fn main() {}\n')
    copied=[]
    # Owner-level tests cover native clipboard effects. This TUI test verifies
    # the click path without touching the real desktop clipboard.
    async def capture_copy(self, text, source):
        copied.append(text)
    monkeypatch.setattr(TUIApp,'_request_clipboard_copy',capture_copy)
    async def run():
        from isycode.file_preview import FilePreviewScreen
        from textual.widgets import Tree,TextArea
        app=TUIApp()
        async with app.run_test(size=(120,40)) as p:
            async def wait_for_copy(expected):
                for _ in range(40):
                    if copied and copied[-1] == expected:
                        return
                    await p.pause(0.05)
                assert copied and copied[-1] == expected
            await p.pause();app._set_rail_view('files');await app._load_directory(str(root))
            tree=app.query_one('#workspace-tree',Tree)
            leaf=None
            for _ in range(40):
                leaf=next((node for node in tree.root.children
                           if Path(node.data['path']).resolve()==file.resolve()),None)
                if leaf is not None:
                    break
                await p.pause(0.05)
            assert leaf is not None
            assert not leaf.allow_expand
            tree.select_node(leaf);await p.pause()
            assert not app.query_one('#file-copy-path').disabled
            for _ in range(20):
                if app._selected_file_path == str(file):
                    break
                await p.pause(0.05)
            assert app._selected_file_path == str(file)
            from textual.widgets import Button
            await app.on_button_pressed(Button.Pressed(app.query_one('#file-copy-path',Button)))
            await wait_for_copy(str(file))
            await app.on_button_pressed(Button.Pressed(app.query_one('#file-open-preview',Button)))
            # Opening the preview runs in a Textual worker. A single pause
            # does not guarantee that its screen has been pushed on slow CI.
            for _ in range(40):
                if (isinstance(app.screen, FilePreviewScreen) and app.screen.is_mounted
                        and app.screen.query('#preview-copy')):
                    break
                await p.pause(0.05)
            assert isinstance(app.screen, FilePreviewScreen)
            editor=app.screen.query_one(TextArea);assert editor.read_only and editor.text==file.read_bytes().decode('utf-8')
            assert app.screen.query_one('#preview-copy').disabled
            await p.click('#preview-copy');await wait_for_copy(str(file))
            from textual.document._document import Selection
            editor.selection=Selection((0,3),(0,7));await p.pause()
            await p.click('#preview-copy');await wait_for_copy('main')
            await p.click('#preview-copy-whole');await wait_for_copy(file.read_bytes().decode('utf-8'))
            await p.press('escape')
    with capsys.disabled():asyncio.run(run())

def test_copy_path_for_selected_directory(tmp_path,monkeypatch,capsys):
    root=configure(tmp_path,monkeypatch);folder=root/'subfolder';folder.mkdir()
    copied=[];monkeypatch.setattr(TUIApp,'_copy_through_owner',lambda self,text,source:copied.append(text))
    async def scenario():
        from textual.widgets import Tree
        from isycode.workspace_authority import WorkspaceAuthority
        app=TUIApp()
        async with app.run_test(size=(100,30)) as pilot:
            await pilot.pause();app._set_rail_view('files');await app._load_directory(str(root))
            tree=app.query_one('#workspace-tree',Tree)
            node=next(n for n in tree.root.children if n.data['path']==str(folder))
            tree.select_node(node)
            copy_path=app.query_one('#file-copy-path')
            for _ in range(20):
                await pilot.pause(0.05)
                if not copy_path.disabled:
                    break
            assert not copy_path.disabled
            assert app.query_one('#file-open-preview').disabled
            WorkspaceAuthority(root).set_grant('clipboard.copy',enabled=True,targets=['clipboard'])
            await pilot.click('#file-copy-path')
            for _ in range(40):
                if copied:
                    break
                await pilot.pause(0.05)
            assert copied==[str(folder)]
    with capsys.disabled():asyncio.run(scenario())
