"""Synthetic storage observations test policy, never real VHD acceptance."""
from dataclasses import replace
from pathlib import Path
import os
import pytest

from isycode.platform_windows_sandbox_volume import (
    MAX_STORAGE_BYTES, StorageConfig, StorageIdentity, VolumeObservation,
    StorageUnavailableError, validate_observation,
)

GUID = '\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\'


@pytest.fixture
def config():
    return StorageConfig(GUID, Path('C:/synthetic/fixed.vhd'), MAX_STORAGE_BYTES)


@pytest.fixture
def observation():
    identity = StorageIdentity(GUID, 42, 'synthetic-image-id', 'synthetic-file-id',
                               MAX_STORAGE_BYTES, MAX_STORAGE_BYTES)
    return VolumeObservation(identity, 'NTFS', 2, True, True, True, True)


def test_exact_capacity_is_accepted(config, observation):
    assert validate_observation(config, observation) == observation.identity


@pytest.mark.parametrize('capacity', [536870913, 0, -1, True])
def test_invalid_capacity_refused(config, observation, capacity):
    value = replace(observation, identity=replace(observation.identity, capacity_bytes=capacity))
    with pytest.raises(StorageUnavailableError):
        validate_observation(config, value)


@pytest.mark.parametrize('field,value', [('filesystem', 'FAT32'), ('filesystem', 'ReFS'),
    ('device_id', 1), ('device_id', 3), ('fixed', False), ('attached_matches', False),
    ('private_root', False), ('private_backing', False)])
def test_unsupported_or_untrusted_storage_refused(config, observation, field, value):
    with pytest.raises(StorageUnavailableError):
        validate_observation(config, replace(observation, **{field: value}))


def test_wrong_guid_refused(config, observation):
    with pytest.raises(StorageUnavailableError):
        validate_observation(config, replace(observation, identity=replace(
            observation.identity, volume_guid=GUID.replace('11111111', '99999999'))))


@pytest.mark.parametrize('guid', ['C:/', 'D:/', '../escape', GUID + 'folder', '\\\\host\\share\\'])
def test_guid_requires_full_volume_root(config, observation, guid):
    with pytest.raises(StorageUnavailableError):
        validate_observation(replace(config, volume_guid=guid), observation)


@pytest.mark.parametrize('maximum', [True, 0, 536870913, 536870911])
def test_policy_maximum_cannot_be_changed(config, observation, maximum):
    with pytest.raises(StorageUnavailableError):
        validate_observation(replace(config, max_bytes=maximum), observation)


@pytest.mark.skipif(os.name != 'nt', reason='native handle adapter fake')
def test_provider_retains_and_rechecks_handles(config, observation, tmp_path, monkeypatch):
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    import isycode.platform_windows_sandbox_volume_api as api
    class Holder:
        root = tmp_path
        closed = False
        def refresh(self): return self.current
        def contains_directory(self, path): return path.parent == self.root
        def close(self): self.closed = True
    holder = Holder()
    holder.current = observation
    holder.observation = observation
    monkeypatch.setattr(api, 'open_volume_handles', lambda _: holder)
    lease = BoundedStorageProvider(config).open()
    assert not holder.closed
    lease.assert_directory(tmp_path / 'owned')
    holder.current = replace(observation, identity=replace(observation.identity, volume_serial=99))
    with pytest.raises(StorageUnavailableError):
        lease.assert_unchanged()
    lease.close()
    assert holder.closed


@pytest.mark.skipif(os.name != 'nt', reason='native handle adapter fake')
def test_registration_identity_change_closes_handles(config, observation, tmp_path, monkeypatch):
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    import isycode.platform_windows_sandbox_volume_api as api
    class Holder:
        root = tmp_path
        closed = False
        def close(self): self.closed = True
    holder = Holder()
    holder.observation = observation
    monkeypatch.setattr(api, 'open_volume_handles', lambda _: holder)
    expected = replace(observation.identity, backing_file_id='old-file')
    with pytest.raises(StorageUnavailableError):
        BoundedStorageProvider(replace(config, registered_identity=expected)).open()
    assert holder.closed
