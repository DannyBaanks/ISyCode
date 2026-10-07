import json

import pytest

from isycode.workspace_authority import WorkspaceAuthority


def make_store(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    main = tmp_path / 'main'
    other = tmp_path / 'Other Project'
    main.mkdir()
    other.mkdir()
    WorkspaceAuthority(main).set_mode('classic')
    from isycode.workspace_folders import WorkspaceFolders
    return WorkspaceFolders(main), main, other


def test_attached_folder_persists_with_exact_file_grants(tmp_path, monkeypatch):
    store, main, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=True)
    assert type(store)(main).resolve('other', write=True) == other
    policy = WorkspaceAuthority(other).effective_policy()['grants']
    assert policy['workspace.files.write']['path_prefixes'] == [str(other)]
    assert 'provider.request' not in policy and 'workspace.command.run' not in policy
    assert WorkspaceAuthority(main).policy()['grants'] == {}


def test_read_only_attachment_caps_a_classic_workspace(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    WorkspaceAuthority(other).set_mode('classic')
    store.add('other', str(other), editable=False)
    assert store.resolve('other') == other
    with pytest.raises(ValueError):
        store.resolve('other', write=True)
    with pytest.raises(ValueError):
        store.set_auto_edit('other', True)


@pytest.mark.parametrize('bad', ['parent', 'child', 'missing', 'symlink'])
def test_only_real_sibling_directories_can_be_attached(tmp_path, monkeypatch, bad):
    store, main, other = make_store(tmp_path, monkeypatch)
    child = main / 'child'
    child.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(other, target_is_directory=True)
    path = {'parent': tmp_path, 'child': child, 'missing': tmp_path / 'missing', 'symlink': link}[bad]
    with pytest.raises(ValueError):
        store.add('other', str(path), editable=True)
    assert store.list() == []


def test_replaced_root_and_removed_alias_do_not_route(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=True)
    other.rename(tmp_path / 'old')
    other.mkdir()
    with pytest.raises(ValueError):
        store.resolve('other')
    store.remove('other')
    with pytest.raises(ValueError):
        store.resolve('other')


def test_auto_edit_preference_is_disabled_by_default_and_root_scoped(tmp_path, monkeypatch):
    store, main, other = make_store(tmp_path, monkeypatch)
    WorkspaceAuthority(other).set_mode('classic')
    store.add('other', str(other), editable=True)
    assert not store.auto_edit_allowed('main') and not store.auto_edit_allowed('other')
    store.set_auto_edit('other', True)
    assert type(store)(main).auto_edit_allowed('other')
    assert not store.auto_edit_allowed('main')
    store.set_auto_edit('other', False)
    assert not store.auto_edit_allowed('other')
    store.set_auto_edit('main', True)
    assert WorkspaceAuthority(main).policy()['grants'] == {}


def test_corrupt_or_unsafe_config_fails_closed(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=True)
    store.path.write_text('{broken')
    with pytest.raises(ValueError):
        store.resolve('other')
    with pytest.raises(ValueError):
        store.auto_edit_allowed('main')
    assert store.path.read_text() == '{broken'


def test_aliases_duplicates_and_limits_are_validated(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    for alias in ['main', '../other', '', 'other folder']:
        with pytest.raises(ValueError):
            store.add(alias, str(other), editable=True)
    store.add('other', str(other), editable=True)
    with pytest.raises(ValueError):
        store.add('duplicate', str(other), editable=True)
    for n in range(7):
        p = tmp_path / f'folder{n}'
        p.mkdir()
        store.add(f'folder{n}', str(p), editable=False)
    extra = tmp_path / 'extra'
    extra.mkdir()
    with pytest.raises(ValueError):
        store.add('extra', str(extra), editable=True)

@pytest.mark.parametrize('name', ['.ssh', '.git', 'state'])
def test_sensitive_roots_and_internal_state_cannot_be_attached(tmp_path, monkeypatch, name):
    store, _, _ = make_store(tmp_path, monkeypatch)
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    with pytest.raises(ValueError):
        store.add('sensitive', str(folder), editable=True)


def test_private_state_inside_primary_cannot_enable_delegation(tmp_path, monkeypatch):
    main = tmp_path / 'project'
    main.mkdir()
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(main / 'state'))
    from isycode.workspace_folders import WorkspaceFolders
    with pytest.raises(ValueError, match='outside'):
        WorkspaceFolders(main)


def _enabled(root):
    return {action for action, grant in WorkspaceAuthority(root).policy()['grants'].items()
            if grant.get('enabled')}


def test_removing_a_folder_revokes_only_what_attaching_it_granted(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    # The user had already allowed reading that folder on their own.
    WorkspaceAuthority(other).set_grant('workspace.files.read', enabled=True, path_prefixes=[str(other)])
    store.add('other', str(other), editable=True)
    assert _enabled(other) == {'workspace.files.list', 'workspace.files.read',
                               'workspace.files.search', 'workspace.files.write'}
    revoked = store.remove('other')
    assert sorted(revoked) == ['workspace.files.list', 'workspace.files.search', 'workspace.files.write']
    assert _enabled(other) == {'workspace.files.read'}


def test_removing_a_legacy_registration_revokes_the_grants_it_always_set(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=False)
    data = json.loads(store.path.read_text())
    del data['folders'][0]['granted']  # saved before grants were recorded
    store._save(data)
    assert sorted(store.remove('other')) == ['workspace.files.list', 'workspace.files.read',
                                             'workspace.files.search']
    assert _enabled(other) == set()


def test_recorded_grants_cannot_claim_write_on_a_read_only_folder(tmp_path, monkeypatch):
    store, _, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=False)
    data = json.loads(store.path.read_text())
    data['folders'][0]['granted'].append('workspace.files.write')
    store._save(data)
    with pytest.raises(ValueError):
        store.list()


@pytest.mark.parametrize('secured', ['main', 'other'])
def test_security_mode_suspends_saved_automatic_edits(tmp_path, monkeypatch, secured):
    store, main, other = make_store(tmp_path, monkeypatch)
    WorkspaceAuthority(other).set_mode('classic')
    store.add('other', str(other), editable=True)
    store.set_auto_edit('other', True)
    WorkspaceAuthority(main if secured == 'main' else other).set_mode('security')
    assert not store.auto_edit_allowed('other')
    with pytest.raises(ValueError, match='Security'):
        store.set_auto_edit('other', True)
    store.set_auto_edit('other', False)
    assert not store.auto_edit_allowed('other')


@pytest.mark.parametrize('policy', ['unconfigured', 'corrupt'])
def test_unconfigured_or_unreadable_attachment_cannot_delegate(tmp_path, monkeypatch, policy):
    store, _, other = make_store(tmp_path, monkeypatch)
    store.add('other', str(other), editable=True)
    if policy == 'corrupt':
        WorkspaceAuthority(other).policy_path.write_text('{broken')
    assert not store.auto_edit_allowed('other')
    with pytest.raises(ValueError, match='Security'):
        store.set_auto_edit('other', True)
    store.set_auto_edit('other', False)
    assert not store.auto_edit_allowed('other')
