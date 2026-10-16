import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows cleanup')


def test_substituted_volume_refused_before_copy(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    class Unavailable:
        root = tmp_path
        def assert_unchanged(self): raise OSError('changed volume')
    with pytest.raises(OSError, match='changed volume'):
        WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), (),
                                        storage_lease=Unavailable())
    assert list(tmp_path.iterdir()) == []


def test_schema2_recovery_requires_volume_before_deletion(tmp_path):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    root = Path(tmp_path.anchor) / 'isycode-lpac-testvol2'
    from isycode.platform_windows_storage import WindowsStorage
    WindowsStorage().ensure_directory(root)
    record = root / 'ownership.json'
    try:
        record.write_text(json.dumps({'schema': 'isycode-native-scratch/2'}))
        WindowsStorage().protect(record)
        with pytest.raises(ValueError, match='storage configuration'):
            recover_owned_scratch(root)
        assert record.exists()
    finally:
        record.unlink(missing_ok=True)
        root.rmdir()


def test_schema2_recovery_refuses_wrong_volume(tmp_path, monkeypatch):
    from isycode.platform_windows_sandbox_recovery import write_ownership, recover_owned_scratch, PROFILE_PREFIX
    from isycode.platform_windows_sandbox_resources import _profile_sid
    from isycode.platform_windows_sandbox_volume import StorageIdentity, BoundedStorageProvider, StorageUnavailableError
    from isycode.platform_windows_storage import WindowsStorage
    root = Path(tmp_path.anchor) / ('isycode-lpac-' + secrets.token_hex(4))
    WindowsStorage().ensure_directory(root)
    identity = StorageIdentity('synthetic', 1, 'image', 'file', 536870912, 536870912)
    name = PROFILE_PREFIX + '1' * 32
    write_ownership(root, name, _profile_sid(name), storage_identity=identity)
    before = (root / 'ownership.json').read_bytes()
    def reject(_self, expected):
        assert expected == identity
        raise StorageUnavailableError('wrong volume control')
    monkeypatch.setattr(BoundedStorageProvider, 'open', reject)
    try:
        with pytest.raises(StorageUnavailableError, match='wrong volume'):
            recover_owned_scratch(root, storage_config=object())
        assert (root / 'ownership.json').read_bytes() == before
    finally:
        (root / 'ownership.json').unlink()
        root.rmdir()


def test_root_acl_unchanged_after_allocation(tmp_path, synthetic_windows_storage):
    import win32security as security
    from isycode.platform_windows_sandbox import WindowsSandbox
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    def snapshot(path):
        descriptor = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        return security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor,
            security.SDDL_REVISION_1, security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    with WindowsSandbox()._provider().open() as lease:
        before = snapshot(lease.root)
        with WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), (), storage_lease=lease) as resource:
            assert resource.scratch_root.parent == lease.root
            assert json.loads((resource.scratch_root / 'ownership.json').read_text())['schema'] == 'isycode-native-scratch/2'
            assert snapshot(lease.root) == before
        assert snapshot(lease.root) == before


def test_recovery_refuses_unowned_folder(tmp_path):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    with pytest.raises(ValueError, match='ownership'):
        recover_owned_scratch(tmp_path)


def test_recovery_after_creator_death(tmp_path):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    source = tmp_path / 'source'
    source.mkdir()
    code = '''import sys,os,json
from pathlib import Path
from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
r=WindowsSandboxResources.prepare(Path(sys.argv[1]),Path(sys.base_prefix),())
print(json.dumps({'root':str(r.scratch_root)}),flush=True)
os._exit(0)
'''
    process = subprocess.run([sys.executable, '-c', code, str(source)],
        capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[1] / 'src')
    assert process.returncode == 0, process.stderr
    root = Path(json.loads(process.stdout)['root'])
    assert root.exists()
    assert recover_owned_scratch(root) == 'RECOVERED'
    assert not root.exists()


def test_profile_failure_still_erases_scratch_data(tmp_path, monkeypatch):
    import isycode.platform_windows_sandbox_resources as native
    resource = native.WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ())
    real_delete = native.userenv.DeleteAppContainerProfile
    try:
        monkeypatch.setattr(native.userenv, 'DeleteAppContainerProfile', lambda _: -1)
        with pytest.raises(OSError):
            resource.close()
        assert not resource.runtime_root.exists()
        assert not resource.stage_root.exists()
        assert (resource.scratch_root / 'ownership.json').exists()
    finally:
        monkeypatch.setattr(native.userenv, 'DeleteAppContainerProfile', real_delete)
        resource.close()


@pytest.mark.parametrize('crash', ['copy', 'profile-created'])
def test_recovery_covers_preparation_crash_windows(tmp_path, crash):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    source = tmp_path / 'source'
    source.mkdir()
    code = '''import sys,os,json
from pathlib import Path
import isycode.platform_windows_sandbox_resources as native
if sys.argv[2]=='copy':
 def die_copy(source,target,*args,**kwargs):
  Path(target).mkdir(); Path(target,'partial.txt').write_text('partial-control')
  print(json.dumps({'root':str(Path(target).parent)}),flush=True); os._exit(0)
 native.shutil.copytree=die_copy
else:
 real_record=native.write_ownership
 def die_record(root,name,sid,*,phase='ALLOCATED'):
  if phase=='PROFILE_CREATED':
   print(json.dumps({'root':str(root)}),flush=True); os._exit(0)
  return real_record(root,name,sid,phase=phase)
 native.write_ownership=die_record
native.WindowsSandboxResources.prepare(Path(sys.argv[1]),Path(sys.base_prefix),())
'''
    process = subprocess.run([sys.executable, '-c', code, str(source), crash],
        capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[1] / 'src')
    assert process.returncode == 0, process.stderr
    root = Path(json.loads(process.stdout)['root'])
    assert recover_owned_scratch(root) == 'RECOVERED'
    assert not root.exists()
