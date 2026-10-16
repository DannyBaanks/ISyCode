import json
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native private storage registration')


@pytest.fixture
def private_dir(tmp_path):
    from isycode.platform_windows_storage import WindowsStorage
    private = tmp_path / 'operator-private'
    WindowsStorage().ensure_directory(private)
    return private


def test_failed_inspection_never_writes_config(private_dir, monkeypatch):
    import isycode.windows_sandbox_storage_cli as cli
    from isycode.platform_windows_sandbox_volume import StorageConfig, StorageUnavailableError
    def fail(_):
        raise StorageUnavailableError('inspection control')
    monkeypatch.setattr(cli, 'inspect_volume', fail)
    dest = private_dir / 'storage.json'
    with pytest.raises(StorageUnavailableError):
        cli.register_storage_config(StorageConfig(
            '\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\', Path('fake.vhd')), dest)
    assert not dest.exists()


def test_register_private_config_and_readback(private_dir, monkeypatch):
    import isycode.windows_sandbox_storage_cli as cli
    from isycode.platform_windows_sandbox_volume import StorageConfig, StorageIdentity, VolumeObservation
    from isycode.platform_windows_storage import WindowsStorage
    guid = '\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\'
    config = StorageConfig(guid, private_dir / 'fixed.vhd')
    identity = StorageIdentity(guid, 42, 'image', 'file', 536870912, 536870912)
    # Synthetic SDK observation: tests registration only, not real VHD capacity.
    monkeypatch.setattr(cli, 'inspect_volume', lambda _: VolumeObservation(identity, 'NTFS', 2, True, True, True, True))
    dest = private_dir / 'storage.json'
    assert cli.register_storage_config(config, dest) == identity
    assert WindowsStorage().private(dest)
    assert cli.load_storage_config(dest).registered_identity == identity
    before = dest.read_bytes()
    assert cli.register_storage_config(config, dest) == identity
    assert dest.read_bytes() == before


def test_existing_different_config_preserved(private_dir, monkeypatch):
    import isycode.windows_sandbox_storage_cli as cli
    from isycode.platform_windows_sandbox_volume import StorageConfig, StorageUnavailableError, StorageIdentity, VolumeObservation
    from isycode.platform_windows_storage import WindowsStorage
    dest = private_dir / 'storage.json'
    guid = '\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\'
    config = StorageConfig(guid, private_dir / 'fixed.vhd')
    identity = StorageIdentity(guid, 42, 'image', 'file', 536870912, 536870912)
    monkeypatch.setattr(cli, 'inspect_volume', lambda _: VolumeObservation(identity, 'NTFS', 2, True, True, True, True))
    cli.register_storage_config(config, dest)
    before = dest.read_bytes()
    with pytest.raises(StorageUnavailableError):
        cli.register_storage_config(StorageConfig(guid, private_dir / 'different.vhd'), dest)
    assert dest.read_bytes() == before


def test_public_config_refused_without_acl_repair(private_dir):
    import win32security as security
    import isycode.windows_sandbox_storage_cli as cli
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    from isycode.platform_windows_storage import WindowsStorage
    dest = private_dir / 'storage.json'
    dest.write_text('{}')
    WindowsStorage().protect(dest)
    descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;;FA;;;WD)', security.SDDL_REVISION_1)
    security.SetNamedSecurityInfo(str(dest), security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)
    def acl():
        return security.GetNamedSecurityInfo(str(dest), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl().GetAce(0)
    before = acl()
    with pytest.raises(StorageUnavailableError): cli.load_storage_config(dest)
    assert acl() == before


@pytest.mark.parametrize('contents', ['not-json', '{}', '{"schema":"other"}', '[]'])
def test_invalid_config_is_refused(private_dir, contents):
    import isycode.windows_sandbox_storage_cli as cli
    from isycode.platform_windows_sandbox_volume import StorageUnavailableError
    from isycode.platform_windows_storage import WindowsStorage
    dest = private_dir / 'storage.json'
    dest.write_text(contents)
    WindowsStorage().protect(dest)
    with pytest.raises(StorageUnavailableError):
        cli.load_storage_config(dest)


def test_cli_has_no_disk_mutator_commands(capsys):
    import isycode.windows_sandbox_storage_cli as cli
    with pytest.raises(SystemExit) as result:
        cli.main(['--help'])
    assert result.value.code == 0
    text = capsys.readouterr().out
    assert 'inspect-image' in text and 'register' in text
    assert '{inspect-image,inspect-volume,register}' in text
