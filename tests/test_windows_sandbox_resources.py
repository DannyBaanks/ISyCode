"""Real filesystem/registry/network witnesses for native isolation."""
import hashlib
import os
from pathlib import Path
import socket
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows isolation')


def test_runtime_copy_ignores_optional_python_launcher_alias(tmp_path):
    from isycode.platform_windows_sandbox_resources import runtime_files
    runtime = tmp_path / 'cpython'
    runtime.mkdir()
    (runtime / 'python.exe').write_bytes(b'python-control')
    # Actions Windows may install python3.exe as an app-execution alias rather
    # than a regular executable. It is not the interpreter this backend runs.
    (runtime / 'python3.exe').mkdir()
    assert [name for name, _ in runtime_files(runtime)] == ['python.exe']


@pytest.fixture
def prepared(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    stage = tmp_path / 'stage'
    stage.mkdir()
    with WindowsSandboxResources.prepare(stage, Path(sys.base_prefix), ()) as resources:
        yield resources


def run(resources, code):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    exe = resources.runtime_root / 'python.exe'
    with WindowsSandboxProcess.launch(exe, (str(exe), '-I', '-c', code),
            resources.stage_root, resources.environment, resources.profile_sid,
            256, resources.capability_sids) as process:
        status = process.wait(20)
        output = process.read(8192)
    assert status == 0, output.decode(errors='replace')
    return output


def test_runtime_copy_preserves_executable_bytes(prepared):
    original = Path(sys.base_prefix) / 'python.exe'
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(
        (prepared.runtime_root / 'python.exe').read_bytes()).digest()


def test_stage_writable_but_runtime_readonly(prepared):
    output = run(prepared, 'from pathlib import Path; import sys; '
        'Path("result.txt").write_text("stage-result"); '
        'p=Path(sys.executable);\ntry: p.write_bytes(b"changed")\n'
        'except PermissionError: print("runtime-denied")\nelse: raise RuntimeError("runtime writable")')
    assert b'runtime-denied' in output
    assert (prepared.stage_root / 'result.txt').read_text() == 'stage-result'


@pytest.mark.parametrize('kind', ['tcp', 'udp'])
@pytest.mark.parametrize('family', ['ipv4', 'ipv6'])
def test_network_denied_with_host_witness(prepared, kind, family):
    socktype = socket.SOCK_STREAM if kind == 'tcp' else socket.SOCK_DGRAM
    address_family = socket.AF_INET if family == 'ipv4' else socket.AF_INET6
    address = '127.0.0.1' if family == 'ipv4' else '::1'
    if family == 'ipv6' and not socket.has_ipv6:
        pytest.skip('host IPv6 witness unavailable; NOT_DEMONSTRATED')
    with socket.socket(address_family, socktype) as witness:
        witness.bind((address, 0))
        if kind == 'tcp':
            witness.listen(1)
        port = witness.getsockname()[1]
        with socket.socket(address_family, socktype) as host_control:
            if kind == 'tcp':
                host_control.connect((address, port))
                host_control.sendall(b'host-control')
                accepted, _ = witness.accept()
                with accepted:
                    assert accepted.recv(1024) == b'host-control'
            else:
                host_control.sendto(b'host-control', (address, port))
                assert witness.recvfrom(1024)[0] == b'host-control'
        operation = (f's.connect(({address!r},{port}))' if kind == 'tcp'
                     else f's.sendto(b"witness",({address!r},{port}))')
        output = run(prepared, f'import socket;\ntry:\n s=socket.socket({address_family},{socktype}); '
            f's.settimeout(1); {operation}\n'
            'except PermissionError: print("network-denied")\nelse: raise RuntimeError("network allowed")')
        assert b'network-denied' in output
        witness.settimeout(0.2)
        with pytest.raises(TimeoutError):
            witness.accept() if kind == 'tcp' else witness.recvfrom(1024)


def test_registry_read_does_not_open_private_key(prepared):
    import secrets
    import winreg
    import win32api
    import win32con
    import win32security as security
    from isycode.platform_windows_storage import WindowsStorage
    name = 'Software\\ISyCodeIsolationControl\\' + secrets.token_hex(12)
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_ALL_ACCESS)
    try:
        winreg.SetValueEx(key, 'seed', 0, winreg.REG_SZ, 'seeded-not-real-secret')
        user = security.ConvertSidToStringSid(WindowsStorage()._user())
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f'D:P(A;;KA;;;{user})(A;;KA;;;SY)', 1)
        security.SetSecurityInfo(int(key), security.SE_REGISTRY_KEY,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, descriptor.GetSecurityDescriptorDacl(), None)
        output = run(prepared, f'import winreg;\ntry: winreg.OpenKey(winreg.HKEY_CURRENT_USER,{name!r})\n'
            'except (PermissionError,FileNotFoundError): print("private-key-denied")\n'
            'else: raise RuntimeError("private key accessible")')
        assert b'private-key-denied' in output
        assert winreg.QueryValueEx(key, 'seed')[0] == 'seeded-not-real-secret'
    finally:
        key.Close()
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)


def test_marker_cannot_be_deleted_or_changed(prepared):
    # Re-prepare after placing the marker, so it gets its special policy.
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    source = prepared.stage_root
    (source / '.isyroot').write_text('marker-control')
    with WindowsSandboxResources.prepare(source, Path(sys.base_prefix), ()) as resources:
        output = run(resources, 'from pathlib import Path; p=Path(".isyroot"); '
            '\nfor op in [lambda:p.write_text("changed"),lambda:p.unlink()]:\n'
            ' try: op()\n except PermissionError: print("marker-denied")\n'
            ' else: raise RuntimeError("marker modified")')
        assert output.count(b'marker-denied') == 2
        assert (resources.stage_root / '.isyroot').read_text() == 'marker-control'


def test_sensitive_masks_remove_secret_and_alias(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    source = tmp_path / 'source'
    source.mkdir()
    (source / '.env').write_text('seeded-secret')
    (source / 'alias.txt').write_text('seeded-secret')
    masks = (('.env', False), ('alias.txt', False))
    with WindowsSandboxResources.prepare(source, Path(sys.base_prefix), masks) as resources:
        assert not (resources.stage_root / '.env').exists()
        assert not (resources.stage_root / 'alias.txt').exists()


def test_unreviewed_secret_refuses_preparation(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    (tmp_path / '.env').write_text('seeded-secret')
    with pytest.raises(ValueError, match='sensitive'):
        WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ())


def test_hardlink_refuses_preparation(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    (tmp_path / 'a.txt').write_text('a')
    os.link(tmp_path / 'a.txt', tmp_path / 'b.txt')
    with pytest.raises(ValueError, match='hardlink'):
        WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ())


def test_marker_owner_cannot_replace_dacl(prepared):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    (prepared.stage_root / '.isyroot').write_text('marker-control')
    with WindowsSandboxResources.prepare(prepared.stage_root, Path(sys.base_prefix), ()) as resources:
        code = '''import ctypes as c
a=c.WinDLL('advapi32',use_last_error=True)
a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[c.c_wchar_p,c.c_ulong,c.POINTER(c.c_void_p),c.c_void_p]
a.SetFileSecurityW.argtypes=[c.c_wchar_p,c.c_ulong,c.c_void_p]
p=c.c_void_p()
assert a.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:(A;;FA;;;WD)',1,c.byref(p),None)
ok=a.SetFileSecurityW('.isyroot',4,p)
assert not ok and c.get_last_error()==5, ('marker DACL escaped',ok,c.get_last_error())
print('dacl-denied')
'''
        assert b'dacl-denied' in run(resources, code)


def test_marker_parent_cannot_be_renamed(prepared):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    nested = prepared.stage_root / 'nested'
    nested.mkdir()
    (nested / '.isyroot').write_text('nested-marker')
    with WindowsSandboxResources.prepare(prepared.stage_root, Path(sys.base_prefix), ()) as resources:
        assert b'parent-denied' in run(resources,
            'from pathlib import Path;\ntry: Path("nested").rename("renamed")\n'
            'except PermissionError: print("parent-denied")\nelse: raise RuntimeError("marker moved")')


def test_insufficient_space_refuses_before_allocation(tmp_path, monkeypatch):
    import isycode.platform_windows_sandbox_resources as native
    from types import SimpleNamespace
    monkeypatch.setattr(native.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(OSError, match='free space'):
        native.WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ())


def test_profile_storage_is_not_an_extra_writable_root(prepared):
    import ctypes as c
    from ctypes import wintypes as w
    import win32security as security
    sid = security.ConvertSidToStringSid(security.SID(prepared.profile_sid))
    get_folder = c.WinDLL('userenv').GetAppContainerFolderPath
    get_folder.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
    get_folder.restype = c.c_long
    pointer = c.c_void_p()
    assert get_folder(sid, c.byref(pointer)) == 0
    free = c.WinDLL('ole32').CoTaskMemFree
    free.argtypes = [c.c_void_p]
    try:
        folder = Path(c.wstring_at(pointer))
    finally:
        free(pointer)
    targets = [folder / 'profile-write-control.txt',
               folder / 'Temp' / 'profile-write-control.txt',
               folder.parent / 'profile-write-control.txt']
    assert folder.exists()
    assert prepared.scratch_root not in folder.parents
    try:
        output = run(prepared, f'from pathlib import Path;\nfor target in {[str(p) for p in targets]!r}:\n'
            ' try: Path(target).write_text("seeded-profile-control")\n'
            ' except PermissionError: print("profile-write-denied")\n'
            ' else: raise RuntimeError("profile storage is an unbounded writable root")\n'
            f'try: Path({str(folder)!r}).rename({str(folder.with_name("AC-renamed"))!r})\n'
            'except PermissionError: print("profile-rename-denied")\n'
            'else: raise RuntimeError("profile storage renamed")')
        assert output.count(b'profile-write-denied') == len(targets)
        assert b'profile-rename-denied' in output
        assert all(not target.exists() for target in targets)
    finally:
        for target in targets:
            target.unlink(missing_ok=True)


def test_profile_registry_write_is_denied(prepared):
    code = '''import ctypes as c, winreg
from ctypes import wintypes as w
api=c.WinDLL('userenv').GetAppContainerRegistryLocation
api.argtypes=[w.DWORD,c.POINTER(c.c_void_p)]; api.restype=c.c_long
key=c.c_void_p()
hr=api(winreg.KEY_SET_VALUE,c.byref(key))
if hr < 0:
 assert hr & 0xffffffff == 0x80070005, ('unexpected registry failure',hex(hr & 0xffffffff))
 print('profile-registry-denied')
else:
 try:
  winreg.SetValueEx(key.value,'isycode.seeded.control',0,winreg.REG_SZ,'seeded-profile-control')
  raise RuntimeError('profile registry is an unbounded writable store')
 except PermissionError: print('profile-registry-denied')
 finally: winreg.CloseKey(key.value)
'''
    assert b'profile-registry-denied' in run(prepared, code)
