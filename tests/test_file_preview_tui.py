import asyncio
from isycode.tui import TUIApp
from test_daily_tui import configure

def test_file_leaf_enables_preview_modal_and_copy_path(tmp_path,monkeypatch,capsys):
    root=configure(tmp_path,monkeypatch);file=root/'hello.rs';file.write_text('fn main() {}\n')
    copied=[]
    from textual.app import App
    monkeypatch.setattr(App,'copy_to_clipboard',lambda self,text:copied.append(text))
    async def run():
        from isycode.file_preview import FilePreviewScreen
        from textual.widgets import Tree,TextArea
        from isycode.workspace_authority import WorkspaceAuthority
        app=TUIApp()
        async with app.run_test(size=(100,30)) as p:
            await p.pause();app._set_rail_view('files');await app._load_directory(str(root))
            tree=app.query_one('#workspace-tree',Tree);leaf=next(n for n in tree.root.children if n.data['path']==str(file))
            assert not leaf.allow_expand
            tree.select_node(leaf);await p.pause()
            assert not app.query_one('#file-copy-path').disabled
            WorkspaceAuthority(root).set_grant('clipboard.copy',enabled=True,targets=['clipboard'])
            await p.click('#file-copy-path');await p.pause();assert copied[-1]==str(file)
            await p.click('#file-open-preview');await p.pause()
            assert isinstance(app.screen,FilePreviewScreen)
            editor=app.screen.query_one(TextArea);assert editor.read_only and editor.text=='fn main() {}\n'
            await p.click('#preview-copy');await p.pause();assert copied[-1]=='fn main() {}\n'
            await p.press('escape')
    with capsys.disabled():asyncio.run(run())

def test_copy_path_for_selected_directory(tmp_path,monkeypatch,capsys):
    root=configure(tmp_path,monkeypatch);folder=root/'subfolder';folder.mkdir()
    from textual.app import App
    copied=[];monkeypatch.setattr(App,'copy_to_clipboard',lambda self,text:copied.append(text))
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
            await pilot.click('#file-copy-path');await pilot.pause();assert copied==[str(folder)]
    with capsys.disabled():asyncio.run(scenario())
