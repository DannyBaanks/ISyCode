"""Explicit config action revocation must win over a broader read grant."""
import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


@pytest.mark.parametrize('mode', ['classic', 'security'])
@pytest.mark.parametrize('action', ['workspace.config.read', 'workspace.config.list'])
def test_config_revocation_wins_over_alias_grant(tmp_path, monkeypatch, mode, action):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'private'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    root = tmp_path / 'project'
    root.mkdir()
    config = root / '.isycode'
    config.mkdir()
    (config / 'config.json').write_text('{"version":1,"default_role":null}')
    authority = WorkspaceAuthority(root)
    authority.set_mode(mode)
    authority.set_grant('workspace.files.read', enabled=True, path_prefixes=[root])
    authority.set_grant('workspace.files.list', enabled=True, path_prefixes=[root])
    authority.set_grant(action, enabled=False)
    relative = '.isycode/config.json' if action.endswith('.read') else '.isycode'
    request = ActionRequest(action, root, str(root / relative), {'path': relative},
                            execution_owner='workspace_read')
    assert not authority.evaluate(request).allowed
    result = LocalWorkspaceReadOwner(root, authority).execute(action, {'path': relative})
    assert result.decision == 'DENY'
    assert 'default_role' not in result.text
