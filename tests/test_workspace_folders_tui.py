from isycode.tui import plain_text
import asyncio
import json

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.tui import TUIApp, WriteApprovalScreen
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_folders import WorkspaceFolders
from test_daily_tui import configure


def setup(tmp_path, monkeypatch, *, editable=True):
    root = configure(tmp_path, monkeypatch)
    sibling = tmp_path / 'Sibling Project'
    sibling.mkdir()
    (sibling / 'file.py').write_text('value = 1\n')
    (root / 'file.py').write_text('value = 10\n')
    store = WorkspaceFolders(root)
    store.add('sibling', str(sibling), editable=editable)
    return root, sibling, store


def call(name, **args):
    return {'id': 'folder-test', 'function': {'name': name, 'arguments': json.dumps(args)}}


def test_sibling_read_and_native_approved_edit_use_its_own_root(tmp_path, monkeypatch, capsys):
    root, sibling, _ = setup(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            _, text = await app._dispatch_chat_tool(call('workspace_read', folder='sibling', path='file.py'))
            assert 'value = 1' in text and 'value = 10' not in text
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen):
                    break
            assert isinstance(app.screen, WriteApprovalScreen)
            assert app.screen.preview.request.workspace_root == sibling
            await pilot.press('tab', 'enter')
            _, result = await asyncio.wait_for(task, 10)
            assert json.loads(result)['status'] == 'written'
            assert (sibling / 'file.py').read_text() == 'value = 2\n'
            assert (root / 'file.py').read_text() == 'value = 10\n'
            assert ActionAuditJournal(sibling).verify().status == 'PASS'

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize('name,args', [
    ('workspace_read', {'folder': 'unknown', 'path': 'file.py'}),
    ('workspace_read', {'folder': 'sibling', 'path': '../project/file.py'}),
    ('workspace_run', {'folder': 'sibling', 'argv': ['echo', 'hello']}),
    ('workspace_delete', {'folder': 'sibling', 'path': 'file.py'}),
])
def test_unknown_alias_traversal_and_unsupported_effects_are_denied(tmp_path, monkeypatch, capsys, name, args):
    _, sibling, _ = setup(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            _, result = await app._dispatch_chat_tool(call(name, **args))
            assert 'error' in json.loads(result)
            assert (sibling / 'file.py').read_text() == 'value = 1\n'

    with capsys.disabled():
        asyncio.run(scenario())


def test_folder_removed_while_diff_is_open_cannot_be_written(tmp_path, monkeypatch, capsys):
    _, sibling, store = setup(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen):
                    break
            store.remove('sibling')
            await pilot.press('tab', 'enter')
            _, result = await asyncio.wait_for(task, 10)
            assert 'error' in json.loads(result)
            assert (sibling / 'file.py').read_text() == 'value = 1\n'

    with capsys.disabled():
        asyncio.run(scenario())


def test_auto_edit_warning_cancel_enable_disable_and_authority_remain(tmp_path, monkeypatch, capsys):
    _, sibling, store = setup(tmp_path, monkeypatch)
    WorkspaceAuthority(sibling).set_mode('classic')

    async def scenario():
        from isycode.tui import AutomaticEditsWarningScreen
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._set_folder_auto_edit('sibling', True))
            await pilot.pause()
            assert isinstance(app.screen, AutomaticEditsWarningScreen)
            await pilot.press('enter')  # Cancel is initially focused.
            await task
            assert not store.auto_edit_allowed('sibling')
            task = asyncio.create_task(app._set_folder_auto_edit('sibling', True))
            await pilot.pause()
            await pilot.click('#auto-edit-enable')
            await task
            assert store.auto_edit_allowed('sibling')
            _, result = await app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2'))
            parsed = json.loads(result)
            assert parsed['status'] == 'written' and parsed['approval_mode'] == 'delegated'
            assert (sibling / 'file.py').read_text() == 'value = 2\n'
            assert ActionAuditJournal(sibling).verify().status == 'PASS'
            WorkspaceAuthority(sibling).set_grant('workspace.files.write', enabled=False)
            _, result = await app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 2', new_text='value = 3'))
            assert 'error' in json.loads(result)
            assert (sibling / 'file.py').read_text() == 'value = 2\n'
            await app._set_folder_auto_edit('sibling', False)
            assert not store.auto_edit_allowed('sibling')

    with capsys.disabled():
        asyncio.run(scenario())


def test_file_browser_selection_keeps_primary_identity(tmp_path, monkeypatch, capsys):
    root, sibling, _ = setup(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app._browse_workspace_folder('sibling')
            assert app._workspace_root == root and app._file_path == str(sibling)
            await app._preview_file(str(sibling / 'file.py'))
            assert 'value = 1' in plain_text(app.query_one('#file-preview'))

    with capsys.disabled():
        asyncio.run(scenario())


def test_readded_alias_invalidates_pending_diff_and_warning(tmp_path, monkeypatch, capsys):
    _, sibling, store = setup(tmp_path, monkeypatch)
    WorkspaceAuthority(sibling).set_mode('classic')

    async def scenario():
        from isycode.tui import AutomaticEditsWarningScreen
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen):
                    break
            assert isinstance(app.screen, WriteApprovalScreen)
            store.remove('sibling')
            store.add('sibling', str(sibling), editable=True)
            await pilot.press('tab', 'enter')
            _, result = await asyncio.wait_for(task, 10)
            assert 'error' in json.loads(result)
            assert (sibling / 'file.py').read_text() == 'value = 1\n'
            task = asyncio.create_task(app._set_folder_auto_edit('sibling', True))
            await pilot.pause()
            assert isinstance(app.screen, AutomaticEditsWarningScreen)
            store.remove('sibling')
            sibling.rename(sibling.with_name('old-sibling'))
            sibling.mkdir()
            store.add('sibling', str(sibling), editable=True)
            await pilot.click('#auto-edit-enable')
            assert not await asyncio.wait_for(task, 10)
            assert not store.auto_edit_allowed('sibling')

    with capsys.disabled():
        asyncio.run(scenario())


def test_native_add_and_always_button_at_80_columns(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    sibling = tmp_path / 'Sibling Project'
    sibling.mkdir()
    (sibling / 'file.py').write_text('value = 1\n')
    store = WorkspaceFolders(root)
    WorkspaceAuthority(sibling).set_mode('classic')

    async def choose_sibling(self):
        return sibling
    monkeypatch.setattr('isycode.tui.SiblingFolderPickerOwner.choose', choose_sibling)

    async def scenario():
        from isycode.tui import AddWorkspaceFolderScreen, AutomaticEditsWarningScreen
        from textual.widgets import Input
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._add_workspace_folder())
            await pilot.pause()
            assert isinstance(app.screen, AddWorkspaceFolderScreen)
            app.screen.query_one('#folder-alias', Input).value = 'sibling'
            button = app.screen.query_one('#folder-add')
            assert button.region.bottom <= 24
            await pilot.click('#folder-add')
            await asyncio.wait_for(task, 10)
            assert store.resolve('sibling') == sibling
            app._close_menu()
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen):
                    break
            await pilot.pause()
            assert app.screen.query_one('#write-approval-always').region.bottom <= 24
            await pilot.click('#write-approval-always')
            await pilot.pause()
            assert isinstance(app.screen, AutomaticEditsWarningScreen)
            assert app.screen.query_one('#auto-edit-enable').region.bottom <= 24
            await pilot.click('#auto-edit-enable')
            _, result = await asyncio.wait_for(task, 10)
            assert json.loads(result)['approval_mode'] == 'delegated'
            assert store.auto_edit_allowed('sibling')
            assert not store.auto_edit_allowed('main')
            _, result = await app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 2', new_text='value = 3'))
            assert json.loads(result)['status'] == 'written'
            assert (sibling / 'file.py').read_text() == 'value = 3\n'
            await app._set_folder_auto_edit('sibling', False)

    with capsys.disabled():
        asyncio.run(scenario())


def test_read_only_attachment_does_not_inherit_classic_write_access(tmp_path, monkeypatch, capsys):
    _, sibling, _ = setup(tmp_path, monkeypatch, editable=False)
    WorkspaceAuthority(sibling).set_mode('classic')

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            _, result = await app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2'))
            assert 'error' in json.loads(result)
            assert (sibling / 'file.py').read_text() == 'value = 1\n'
            assert not await app._set_folder_auto_edit('sibling', True)

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize('size', [(80, 24), (60, 18)])
def test_warning_controls_remain_visible_and_cancel_by_default(tmp_path, monkeypatch, capsys, size):
    root = configure(tmp_path, monkeypatch)

    async def scenario():
        from isycode.tui import AutomaticEditsWarningScreen
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._set_folder_auto_edit('main', True))
            await pilot.pause()
            button = app.screen.query_one('#auto-edit-enable')
            assert button.region.bottom <= size[1]
            assert button.region.right <= size[0]
            await pilot.press('enter')
            assert not await asyncio.wait_for(task, 10)
            assert not WorkspaceFolders(root).auto_edit_allowed('main')

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize('secured', ['main', 'sibling'])
def test_security_requires_review_despite_saved_automatic_edits(tmp_path, monkeypatch, capsys, secured):
    root, sibling, store = setup(tmp_path, monkeypatch)
    WorkspaceAuthority(sibling).set_mode('classic')
    store.set_auto_edit('sibling', True)
    WorkspaceAuthority(root if secured == 'main' else sibling).set_mode('security')

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen) or task.done():
                    break
            assert (sibling / 'file.py').read_text() == 'value = 1\n'
            assert isinstance(app.screen, WriteApprovalScreen)
            assert not app.screen.query('#write-approval-always')
            await pilot.press('enter')
            _, result = await asyncio.wait_for(task, 10)
            assert json.loads(result)['status'] == 'rejected_by_user'
            assert (sibling / 'file.py').read_text() == 'value = 1\n'

    with capsys.disabled():
        asyncio.run(scenario())


def test_security_parent_requires_review_for_trusted_classic_attachment(tmp_path, monkeypatch, capsys):
    from isycode.workspace_trust import WorkspaceTrust, ACCEPT_PHRASE
    root, sibling, _ = setup(tmp_path, monkeypatch)
    authority = WorkspaceAuthority(sibling)
    authority.set_mode('classic')
    WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    WorkspaceAuthority(root).set_mode('security')

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._dispatch_chat_tool(call('workspace_edit', folder='sibling',
                path='file.py', old_text='value = 1', new_text='value = 2')))
            for _ in range(100):
                await pilot.pause(.01)
                if isinstance(app.screen, WriteApprovalScreen) or task.done():
                    break
            assert (sibling / 'file.py').read_text() == 'value = 1\n'
            assert isinstance(app.screen, WriteApprovalScreen)
            await pilot.press('escape')
            _, result = await asyncio.wait_for(task, 10)
            assert json.loads(result)['status'] == 'rejected_by_user'

    with capsys.disabled():
        asyncio.run(scenario())
