import ctypes as c
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Win32 read-only volume probes')


def test_close_failure_still_releases_remaining_handles_and_fd(tmp_path):
    from isycode.platform_windows_sandbox_volume_api import _release
    closed = []
    class Handle:
        def __init__(self, name, fail=False): self.name, self.fail = name, fail
        def Close(self):
            closed.append(self.name)
            if self.fail: raise OSError('close control')
    file = tmp_path / 'owned'
    file.write_bytes(b'test')
    fd = os.open(file, os.O_RDONLY | os.O_BINARY)
    with pytest.raises(OSError, match='close control'):
        _release((Handle('first', True), Handle('second')), fd)
    assert closed == ['first', 'second']
    with pytest.raises(OSError): os.fstat(fd)


def test_sdk_layouts():
    from isycode import platform_windows_sandbox_volume_api as api
    assert c.sizeof(api.GUID) == 16
    assert c.sizeof(api.VIRTUAL_STORAGE_TYPE) == 20
    assert c.sizeof(api.DEPENDENCY_ENTRY) == 64
    assert api.DISK_INFO.data.offset == 8


def test_physical_volume_cannot_supply_virtual_dependency():
    from isycode.platform_windows_sandbox_volume_api import dependencies
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    import win32file
    root = Path(os.environ['SystemRoot']).anchor
    handle = win32file.CreateFile(root, 0x80, 7, None, 3, 0x02000000, None)
    try:
        with pytest.raises(StorageUnavailableError):
            dependencies(handle)
    finally:
        handle.Close()


def test_outside_string_pointer_refused():
    from isycode.platform_windows_sandbox_volume_api import _string
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    buffer = c.create_string_buffer(128)
    with pytest.raises(StorageUnavailableError):
        _string(c.addressof(buffer) + 200, buffer)


def test_mixed_virtual_disk_handles_refused():
    from isycode.platform_windows_sandbox_volume_api import same_physical_device
    assert same_physical_device(r'\\.\PhysicalDrive7', r'\\.\PhysicalDrive7')
    assert not same_physical_device(r'\\.\PhysicalDrive7', r'\\.\PhysicalDrive8')
    assert not same_physical_device(None, r'\\.\PhysicalDrive7')
    assert not same_physical_device('untrusted', 'untrusted')


@pytest.mark.parametrize('count,used', [(2, 72), (1, 71), (1, 1048577), (0, 72)])
def test_truncated_or_ambiguous_dependencies_refused(monkeypatch, count, used):
    import isycode.platform_windows_sandbox_volume_api as api
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    def forged(handle, flags, size, buffer, result):
        api.w.DWORD.from_buffer(buffer, 4).value = count
        c.cast(result, c.POINTER(api.w.ULONG)).contents.value = used
        return 0
    monkeypatch.setattr(api, '_dependencies', forged)
    with pytest.raises(StorageUnavailableError):
        api.dependencies(123)


def test_dependency_string_outside_returned_data_refused():
    import isycode.platform_windows_sandbox_volume_api as api
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    buffer = c.create_string_buffer(128)
    with pytest.raises(StorageUnavailableError):
        api._string(c.addressof(buffer) + 80, buffer, 72)


def test_refresh_rejects_image_handle_for_other_physical_device(tmp_path, monkeypatch):
    """Real ordinary file IDs, synthetic SDK answers; NOT real VHD proof."""
    import isycode.platform_windows_sandbox_volume_api as api
    from isycode.platform_windows_sandbox_volume import (
        StorageConfig, ImageObservation, StorageUnavailableError, validate_observation)
    guid = '\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\'
    image = tmp_path / 'synthetic.vhd'
    image.write_bytes(b'only-a-test-file')
    fd = os.open(image, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    holder = object.__new__(api.VolumeHandleSet)
    holder.config = StorageConfig(guid, image)
    holder.root = Path(guid)
    holder.root_handle, holder.fd, holder.disk = 123, fd, 456
    def volume_name(path, buffer, length):
        buffer.value = guid
        return True
    def volume_info(path, label, length, serial, maximum, flags, filesystem, size):
        filesystem.value = 'NTFS'
        c.cast(serial, c.POINTER(api.w.DWORD)).contents.value = 42
        return True
    def space(path, free, total, physical):
        for pointer in (free, total, physical):
            c.cast(pointer, c.POINTER(c.c_ulonglong)).contents.value = 536870912
        return True
    monkeypatch.setattr(api, '_volume_name', volume_name)
    monkeypatch.setattr(api, '_volume_info', volume_info)
    monkeypatch.setattr(api, '_space', space)
    def drive_type(path):
        assert path.endswith('\\'), 'GetDriveType needs the volume-root separator'
        return 3
    monkeypatch.setattr(api, '_drive_type', drive_type)
    monkeypatch.setattr(api, 'dependencies', lambda _: (
        tmp_path.anchor.rstrip('\\'), str(image.relative_to(tmp_path.anchor)), r'\\.\PhysicalDrive7'))
    monkeypatch.setattr(api, '_image_info', lambda *_: ImageObservation(
        'synthetic-image', 2, True, 536870912, r'\\.\PhysicalDrive8', api._file_id(fd)))
    monkeypatch.setattr(api, '_private_root', lambda _: True)
    monkeypatch.setattr(api.WindowsStorage, 'private', lambda *_args, **_kwargs: True)
    try:
        observation = holder.refresh()
        assert observation.attached_matches is False
        with pytest.raises(StorageUnavailableError):
            validate_observation(holder.config, observation)
    finally:
        os.close(fd)


def test_skipped_acceptance_child_programs_are_valid_python(tmp_path, monkeypatch):
    """Compile generated programs only; no execution or physical quota claim."""
    from types import SimpleNamespace
    import test_windows_sandbox_volume_acceptance as acceptance
    import isycode.platform_windows_sandbox_volume_api as api
    class Compiled(Exception): pass
    def compile_only(resource, code):
        compile(code, '<real-VHD-acceptance-control>', 'exec')
        raise Compiled
    monkeypatch.setattr(acceptance, 'execute', compile_only)
    monkeypatch.setattr(api, 'inspect_image', lambda _: SimpleNamespace(physical_device=r'\\.\PhysicalDrive7'))
    resource = SimpleNamespace(stage_root=tmp_path, scratch_root=tmp_path, profile_root=tmp_path)
    lease = SimpleNamespace(root=tmp_path, config=SimpleNamespace(backing_file=tmp_path / 'image.vhd',
        volume_guid='\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\'))
    (tmp_path / 'image.vhd').write_bytes(b'synthetic')
    for mode in ('sparse', 'compressed'):
        with pytest.raises(Compiled):
            acceptance.test_ntfs_sparse_and_compression_cannot_bypass_file_ceiling((resource, lease), mode)
    for mode in ('many-files', 'temp', 'truncate'):
        with pytest.raises(Compiled):
            acceptance.test_alternate_writes_remain_bounded((resource, lease), mode)
    for target in ('backing', 'root', 'metadata', 'profile'):
        with pytest.raises(Compiled):
            acceptance.test_other_storage_write_paths_denied((resource, lease), target)
    with pytest.raises(Compiled):
        acceptance.test_volume_device_write_handles_denied((resource, lease))
