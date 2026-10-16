"""Native profile identity, caller restoration and non-target ACL witnesses."""
import os
from pathlib import Path
import secrets
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows registry guard')


def _no_thread_token():
    import pywintypes
    import win32api
    import win32con
    import win32security as security
    with pytest.raises(pywintypes.error) as failure:
        security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
    assert failure.value.winerror == 1008


def _launch(resource, code):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    exe = resource.runtime_root / 'python.exe'
    return WindowsSandboxProcess.launch(exe, (str(exe), '-I', '-c', code),
        resource.stage_root, resource.environment, resource.profile_sid,
        256, resource.capability_sids)


@pytest.fixture
def resource(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    with WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ()) as owned:
        yield owned


def test_existing_impersonation_is_refused_and_preserved():
    import win32api
    import win32con
    import win32security as security
    from isycode.platform_windows_sandbox_registry import restrict_profile_registry
    token = security.OpenProcessToken(win32api.GetCurrentProcess(),
                                     win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE)
    try:
        expected = security.GetTokenInformation(token, security.TokenUser)[0]
        security.ImpersonateLoggedOnUser(token)
        try:
            with pytest.raises(OSError, match='existing thread impersonation'):
                restrict_profile_registry(None, b'')
            current = security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
            try:
                actual = security.GetTokenInformation(current, security.TokenUser)[0]
                assert security.ConvertSidToStringSid(actual) == security.ConvertSidToStringSid(expected)
            finally:
                current.Close()
        finally:
            security.RevertToSelf()
    finally:
        token.Close()
    _no_thread_token()


@pytest.mark.parametrize('failure', ['identity', 'discovery', 'acl'])
def test_registry_failure_restores_caller_and_never_resumes(resource, monkeypatch, failure):
    import isycode.platform_windows_sandbox_process as process
    import isycode.platform_windows_sandbox_registry as registry
    from isycode.platform_windows_sandbox_resources import _profile_sid
    def refuse(*args):
        raise OSError(f'{failure} control')
    def resumed(*args):
        raise AssertionError('user code resumed despite guard failure')
    monkeypatch.setattr(process, '_resume', resumed)
    if failure == 'identity':
        actual = registry.restrict_profile_registry
        wrong = _profile_sid('isycode.test.' + secrets.token_hex(16))
        monkeypatch.setattr(process, 'restrict_profile_registry', lambda handle, _: actual(handle, wrong))
        message = 'token does not match'
    else:
        monkeypatch.setattr(registry, '_key_name' if failure == 'discovery' else '_protect_tree', refuse)
        message = f'{failure} control'
    with pytest.raises(OSError, match=message):
        _launch(resource, 'from pathlib import Path; Path("not-resumed.txt").write_text("ran")')
    assert not (resource.stage_root / 'not-resumed.txt').exists()
    _no_thread_token()


def test_guard_does_not_change_other_owned_profile_acls(tmp_path, monkeypatch):
    import winreg
    import win32security as security
    import isycode.platform_windows_sandbox_registry as registry
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    names = {}
    original_name = registry._key_name
    def capture(handle):
        name = original_name(handle)
        names[name.split('\\')[-1]] = name
        return name
    monkeypatch.setattr(registry, '_key_name', capture)
    other_source = tmp_path / 'other'
    other_source.mkdir()
    with WindowsSandboxResources.prepare(other_source, Path(sys.base_prefix), ()) as other:
        with _launch(other, 'print("other-profile")') as process:
            assert process.wait(15) == 0
        relative = names[other.profile_name][len('\\Registry\\User\\'):]
        with winreg.OpenKey(winreg.HKEY_USERS, relative, 0, winreg.KEY_READ) as other_key:
            flags = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            def describe(descriptor):
                return security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor, 1, flags)
            file_before = describe(security.GetFileSecurity(str(other.profile_root), flags))
            registry_before = describe(security.GetSecurityInfo(int(other_key), security.SE_REGISTRY_KEY, flags))
            target_source = tmp_path / 'target'
            target_source.mkdir()
            with WindowsSandboxResources.prepare(target_source, Path(sys.base_prefix), ()) as target:
                # Witness preparation itself, not only launcher registry work.
                assert describe(security.GetFileSecurity(str(other.profile_root), flags)) == file_before
                with _launch(target, 'print("target-profile")') as process:
                    assert process.wait(15) == 0
            assert describe(security.GetFileSecurity(str(other.profile_root), flags)) == file_before
            assert describe(security.GetSecurityInfo(int(other_key), security.SE_REGISTRY_KEY, flags)) == registry_before


def test_registry_read_works_but_key_creation_and_dacl_access_are_denied(resource):
    code = '''import ctypes as c, winreg
from ctypes import wintypes as w
api=c.WinDLL('userenv').GetAppContainerRegistryLocation
api.argtypes=[w.DWORD,c.POINTER(c.c_void_p)]; api.restype=c.c_long
key=c.c_void_p()
assert api(winreg.KEY_READ,c.byref(key))==0
try: winreg.QueryInfoKey(key.value)
finally: winreg.CloseKey(key.value)
for access in (winreg.KEY_CREATE_SUB_KEY, 0x00040000):
 hr=api(access,c.byref(key))
 if hr>=0:
  winreg.CloseKey(key.value)
  raise RuntimeError('registry write or DACL rights available')
 assert hr & 0xffffffff==0x80070005, ('unexpected failure',hex(hr & 0xffffffff))
 print('registry-modification-denied')
'''
    with _launch(resource, code) as process:
        assert process.wait(15) == 0
        assert process.read(8192).count(b'registry-modification-denied') == 2


def test_non_owned_profile_name_is_refused_before_mutation_or_resume(resource, monkeypatch):
    import ctypes as c
    import win32security as security
    import isycode.platform_windows_sandbox_process as process
    import isycode.platform_windows_sandbox_registry as registry
    from isycode.platform_windows_sandbox_resources import userenv, advapi, _profile_folder
    name = 'isycode.control.' + secrets.token_hex(16)
    pointer = c.c_void_p()
    assert userenv.CreateAppContainerProfile(name, name, 'Owned non-target test witness',
                                           None, 0, c.byref(pointer)) == 0
    sid = c.string_at(pointer, advapi.GetLengthSid(pointer))
    advapi.FreeSid(pointer)
    try:
        profile_root = _profile_folder(security.ConvertSidToStringSid(security.SID(sid)), name)
        flags = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
        before = security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            security.GetFileSecurity(str(profile_root), flags), 1, flags)
        def forbidden(*args):
            raise AssertionError('non-owned profile reached registry discovery/mutation or resume')
        monkeypatch.setattr(registry, '_key_name', forbidden)
        monkeypatch.setattr(registry, '_protect_tree', forbidden)
        monkeypatch.setattr(process, '_resume', forbidden)
        exe = resource.runtime_root / 'python.exe'
        with pytest.raises(OSError, match='owned sandbox namespace'):
            with process.WindowsSandboxProcess.launch(exe, (str(exe), '-I', '-c', 'print("not-run")'),
                    resource.stage_root, resource.environment, sid, 256, resource.capability_sids):
                pass
        assert security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            security.GetFileSecurity(str(profile_root), flags), 1, flags) == before
        _no_thread_token()
    finally:
        assert userenv.DeleteAppContainerProfile(name) == 0
