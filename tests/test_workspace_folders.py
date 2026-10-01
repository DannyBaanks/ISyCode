import json

import pytest

from isycode.workspace_authority import WorkspaceAuthority


def make_store(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    main = tmp_path / 'main'
    other = tmp_path / 'Other Project'
    main.mkdir()
    other.mkdir()
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
