"""Operator-provisioned real VHD controls. A missing VHD is NOT_DEMONSTRATED."""
import os
from pathlib import Path
import shutil
import sys
import hashlib

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows VHD acceptance')


@pytest.fixture
def real_storage():
    if not os.environ.get('ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG'):
        pytest.skip('NOT_DEMONSTRATED: operator-provisioned private fixed VHD required')
    from isycode.windows_sandbox_storage_cli import configured_storage
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    config = configured_storage()
    assert shutil.disk_usage(config.backing_file.parent).free >= 1024 ** 3
    with BoundedStorageProvider(config).open():
        pass
    return config


@pytest.fixture
def bounded_resources(tmp_path, real_storage):
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    config = real_storage
    with BoundedStorageProvider(config).open() as lease:
        with WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), (),
                                             storage_lease=lease) as resource:
            yield resource, lease


def execute(resource, code):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    executable = resource.runtime_root / 'python.exe'
    with WindowsSandboxProcess.launch(executable, (str(executable), '-I', '-c', code),
            resource.stage_root, resource.environment, resource.profile_sid,
            256, resource.capability_sids) as process:
        status = process.wait(60)
        output = process.read(8192)
    return status, output


def test_fixed_volume_blocks_513_mib(bounded_resources):
    resource, lease = bounded_resources
    status, output = execute(resource,
        'block=b"x"*1048576\nwith open("budget.bin","wb",buffering=0) as f:\n'
        ' for _ in range(513): f.write(block)\n')
    print('capacity:', lease.identity.capacity_bytes, 'exit:', status,
          'output:', output.decode(errors='replace'))
    assert status != 0
    assert (resource.stage_root / 'budget.bin').stat().st_size <= 536870912
    lease.assert_unchanged()


@pytest.mark.parametrize('mode', ['many-files', 'temp', 'truncate'])
def test_alternate_writes_remain_bounded(bounded_resources, mode):
    resource, lease = bounded_resources
    code = {
        'many-files': 'from pathlib import Path\nfor i in range(131073):\n'
                      ' Path(str(i)).write_bytes(b"x"*4096)\n',
        'temp': 'import os\nwith open(os.path.join(os.environ["TEMP"],"budget.bin"),"wb",buffering=0) as f:\n'
                ' for _ in range(513): f.write(b"x"*1048576)\n',
        'truncate': 'with open("budget.bin","wb") as f: f.truncate(537919488)\n',
    }[mode]
    status, output = execute(resource, code)
    assert status != 0, output
    lease.assert_unchanged()


@pytest.mark.parametrize('mode', ['sparse', 'compressed'])
def test_ntfs_sparse_and_compression_cannot_bypass_file_ceiling(bounded_resources, mode):
    resource, lease = bounded_resources
    control = 0x900c4 if mode == 'sparse' else 0x9c040
    operation = ('f.truncate(537919488)' if mode == 'sparse' else
                 'for _ in range(513): f.write(b"x"*1048576)')
    code = ('import ctypes as c,msvcrt\n'
            'io=c.WinDLL("kernel32",use_last_error=True).DeviceIoControl\n'
            'io.argtypes=[c.c_void_p,c.c_ulong,c.c_void_p,c.c_ulong,c.c_void_p,c.c_ulong,c.c_void_p,c.c_void_p]\n'
            'io.restype=c.c_int\n'
            'with open("budget.bin","wb",buffering=0) as f:\n'
            ' returned=c.c_ulong(); compression=c.c_ushort(1)\n'
            f' ok=io(msvcrt.get_osfhandle(f.fileno()),{control},'
            + ('None,0,' if mode == 'sparse' else 'c.byref(compression),2,')
            + 'None,0,c.byref(returned),None)\n'
            ' if not ok:\n'
            '  assert c.get_last_error()==5, c.get_last_error()\n'
            '  print("control-denied")\n'
            ' else:\n  ' + operation + '\n')
    status, output = execute(resource, code)
    size = (resource.stage_root / 'budget.bin').stat().st_size
    print(mode, 'exit:', status, 'logical bytes:', size, output.decode(errors='replace'))
    assert size <= 536870912, 'physical capacity alone did not bound logical file size'
    assert status != 0 or b'control-denied' in output
    lease.assert_unchanged()


@pytest.mark.parametrize('target', ['backing', 'root', 'metadata', 'profile'])
def test_other_storage_write_paths_denied(bounded_resources, target):
    resource, lease = bounded_resources
    paths = {'backing': lease.config.backing_file, 'root': lease.root,
             'metadata': resource.scratch_root / 'ownership.json',
             'profile': resource.profile_root}
    path = paths[target]
    def fingerprint():
        if target == 'backing':
            # Mounted NTFS metadata changes its contents. Identity is checked
            # by the lease; the fixed image length is the stable witness here.
            return path.stat().st_size
        if not path.is_file():
            return None
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    before = fingerprint()
    status, output = execute(resource,
        'import ctypes as c\nk=c.WinDLL("kernel32",use_last_error=True)\n'
        'k.CreateFileW.argtypes=[c.c_wchar_p,c.c_ulong,c.c_ulong,c.c_void_p,c.c_ulong,c.c_ulong,c.c_void_p]\n'
        'k.CreateFileW.restype=c.c_void_p\nk.CloseHandle.argtypes=[c.c_void_p]\n'
        f'h=k.CreateFileW({str(path)!r},0x40000000,3,None,3,0x02000000,None)\n'
        'if h==c.c_void_p(-1).value:\n assert c.get_last_error()==5,c.get_last_error()\n print("denied")\n'
        'else:\n k.CloseHandle(h)\n raise RuntimeError("write handle escaped scratch")\n')
    assert status == 0 and b'denied' in output, output
    assert fingerprint() == before
    lease.assert_unchanged()


def test_concurrent_allocations_have_distinct_sids_and_no_cross_read(bounded_resources, tmp_path):
    resource, lease = bounded_resources
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    with WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), (), storage_lease=lease) as other:
        assert resource.scratch_root != other.scratch_root
        assert resource.profile_sid != other.profile_sid
        foreign = other.stage_root / 'foreign.txt'
        foreign.write_text('host-positive-read-witness')
        status, output = execute(resource,
            f'from pathlib import Path\ntry: Path({str(foreign)!r}).read_bytes()\n'
            'except PermissionError: print("cross-read-denied")\nelse: raise RuntimeError("cross-read allowed")\n')
        assert status == 0 and b'cross-read-denied' in output, output
        assert foreign.read_text() == 'host-positive-read-witness'


def test_real_volume_owner_promotes_unicode_with_exact_approval(real_storage, tmp_path, monkeypatch):
    import asyncio
    import isycode.platform_windows_sandbox as native
    from isycode.command_runner import CommandRunOwner
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.approvals import ActionApprovalStore
    monkeypatch.setattr(native, 'NATIVE_ACCEPTED', True)  # acceptance harness only
    (tmp_path / '.isyroot').write_text('')
    authority = WorkspaceAuthority(tmp_path)
    authority.set_mode('classic')
    owner = CommandRunOwner(tmp_path, authority, ActionApprovalStore())
    preview = owner.prepare(['python', '-c',
        'from pathlib import Path; Path("resultado ñ con espacios.txt").write_text("verificado",encoding="utf-8")'])
    assert asyncio.run(owner.run(preview, None)).decision == 'DENY'
    outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request)))
    print('real owner result:', outcome)
    assert outcome.decision == 'ALLOW', outcome.text
    assert outcome.receipt is not None
    assert __import__('json').loads(outcome.text)['exit_code'] == 0, outcome.text
    assert (tmp_path / 'resultado ñ con espacios.txt').read_text(encoding='utf-8') == 'verificado'


def test_volume_device_write_handles_denied(bounded_resources):
    resource, lease = bounded_resources
    from isycode.platform_windows_sandbox_volume_api import inspect_image
    physical = inspect_image(lease.config.backing_file).physical_device
    assert physical is not None
    paths = [lease.config.volume_guid.rstrip('\\'), physical]
    status, output = execute(resource,
        'import ctypes as c\nk=c.WinDLL("kernel32",use_last_error=True)\n'
        'k.CreateFileW.argtypes=[c.c_wchar_p,c.c_ulong,c.c_ulong,c.c_void_p,c.c_ulong,c.c_ulong,c.c_void_p]\n'
        'k.CreateFileW.restype=c.c_void_p\nk.CloseHandle.argtypes=[c.c_void_p]\n'
        f'for path in {paths!r}:\n'
        ' h=k.CreateFileW(path,0x40000000,3,None,3,0,None)\n'
        ' if h==c.c_void_p(-1).value: assert c.get_last_error()==5,c.get_last_error()\n'
        ' else: k.CloseHandle(h); raise RuntimeError("device writable")\n'
        'print("device-denied")\n')
    assert status == 0 and b'device-denied' in output, output
    lease.assert_unchanged()
