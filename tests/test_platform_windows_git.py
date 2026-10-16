"""Native Windows Git discovery must not trust project/PATH executables."""
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows registry/ACL adapter')


def test_git_discovery_ignores_fake_path(tmp_path, monkeypatch):
    from isycode.platform_windows_git import WindowsGit
    provider = WindowsGit()
    expected = provider.discover()
    if expected is None:
        pytest.skip('admin-installed Git with verified ACL is unavailable')
    (tmp_path / 'git.exe').write_bytes(b'not a trusted executable')
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert provider.discover() == expected
    assert not provider._trusted(tmp_path / 'git.exe')


def test_git_registry_location_under_user_control_is_refused(tmp_path, monkeypatch):
    import winreg
    from isycode.platform_windows_git import WindowsGit
    root = tmp_path / 'fake-git'
    (root / 'cmd').mkdir(parents=True)
    (root / 'cmd' / 'git.exe').write_bytes(b'fake')
    monkeypatch.setattr(winreg, 'QueryValueEx', lambda *args: (str(root), winreg.REG_SZ))
    assert WindowsGit().discover() is None


def test_git_discovery_refuses_an_unsafe_native_dependency(monkeypatch):
    from isycode.platform_windows_git import WindowsGit
    provider = WindowsGit()
    expected = provider.discover()
    if expected is None:
        pytest.skip('admin-installed Git unavailable')
    original = provider._trusted
    monkeypatch.setattr(provider, '_trusted', lambda path: False if path.suffix.casefold() == '.dll' else original(path))
    assert provider.discover() is None


def test_git_discovery_verifies_intermediate_directories(monkeypatch):
    from isycode.platform_windows_git import WindowsGit
    provider = WindowsGit()
    expected = provider.discover()
    if expected is None:
        pytest.skip('admin-installed Git unavailable')
    intermediate = Path(expected).parent.parent
    original = provider._trusted
    monkeypatch.setattr(provider, '_trusted', lambda path: path != intermediate and original(path))
    assert provider.discover() is None


def test_privacy_refuses_foreign_owner_before_changing_acl(tmp_path, monkeypatch):
    import win32security as security
    from isycode.platform_windows_storage import WindowsStorage
    provider = WindowsStorage()
    path = tmp_path / 'owned.txt'
    path.write_bytes(b'keep')
    flags = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
    def descriptor():
        value = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, flags)
        return security.ConvertSecurityDescriptorToStringSecurityDescriptor(value, security.SDDL_REVISION_1, flags)
    before = descriptor()
    monkeypatch.setattr(provider, '_user', lambda: security.CreateWellKnownSid(security.WinWorldSid, None))
    with pytest.raises(ValueError):
        provider.protect(path)
    assert descriptor() == before
