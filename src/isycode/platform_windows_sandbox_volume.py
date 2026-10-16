"""Bounded storage policy; synthetic observations are not native acceptance."""
from dataclasses import asdict, dataclass
from pathlib import Path
import re

MAX_STORAGE_BYTES = 512 * 1024 ** 2
_VOLUME_GUID = re.compile(r'\\\\\?\\Volume\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}\\', re.I)


class StorageUnavailableError(OSError):
    pass


@dataclass(frozen=True)
class StorageConfig:
    volume_guid: str
    backing_file: Path
    max_bytes: int = MAX_STORAGE_BYTES
    registered_identity: 'StorageIdentity | None' = None


@dataclass(frozen=True)
class StorageIdentity:
    volume_guid: str
    volume_serial: int
    image_identifier: str
    backing_file_id: str
    capacity_bytes: int
    max_bytes: int

    def payload(self):
        return asdict(self)


@dataclass(frozen=True)
class VolumeObservation:
    identity: StorageIdentity
    filesystem: str
    device_id: int
    fixed: bool
    attached_matches: bool
    private_root: bool
    private_backing: bool


@dataclass(frozen=True)
class ImageObservation:
    image_identifier: str
    device_id: int
    fixed: bool
    virtual_bytes: int
    physical_device: str | None
    backing_file_id: str


def validate_config(config):
    if (not isinstance(config.volume_guid, str) or not _VOLUME_GUID.fullmatch(config.volume_guid)
            or type(config.max_bytes) is not int or config.max_bytes != MAX_STORAGE_BYTES):
        raise StorageUnavailableError('storage needs a complete volume GUID and the fixed 512 MiB policy')


def validate_observation(config, observation):
    validate_config(config)
    identity = observation.identity
    if (not isinstance(identity.volume_guid, str)
            or identity.volume_guid.casefold() != config.volume_guid.casefold()
            or type(identity.capacity_bytes) is not int or not 0 < identity.capacity_bytes <= MAX_STORAGE_BYTES
            or type(identity.max_bytes) is not int or identity.max_bytes != config.max_bytes
            or type(identity.volume_serial) is not int or identity.volume_serial < 0
            or not isinstance(identity.image_identifier, str) or not identity.image_identifier
            or not isinstance(identity.backing_file_id, str) or not identity.backing_file_id
            or observation.filesystem != 'NTFS' or type(observation.device_id) is not int
            or observation.device_id != 2
            or any(value is not True for value in (observation.fixed, observation.attached_matches,
                                                   observation.private_root, observation.private_backing))):
        raise StorageUnavailableError('storage identity, capacity, VHD type or private ownership is invalid')
    return identity


class BoundedStorageProvider:
    def __init__(self, config):
        self.config = config

    def open(self, expected=None):
        from isycode.platform_windows_sandbox_volume_api import open_volume_handles
        holder = open_volume_handles(self.config)
        try:
            identity = validate_observation(self.config, holder.observation)
            registered = self.config.registered_identity
            if ((registered is not None and identity != registered)
                    or (expected is not None and identity != expected)):
                raise StorageUnavailableError('bounded storage identity changed after registration or approval')
            return StorageLease(self.config, holder, identity)
        except BaseException:
            holder.close()
            raise


class StorageLease:
    def __init__(self, config, holder, identity):
        self.config, self._holder = config, holder
        self.root, self.identity = holder.root, identity

    def assert_unchanged(self):
        if self._holder is None:
            raise StorageUnavailableError('bounded storage lease is closed')
        current = validate_observation(self.config, self._holder.refresh())
        if current != self.identity:
            raise StorageUnavailableError('bounded storage identity changed during execution')

    def assert_directory(self, path):
        self.assert_unchanged()
        if not self._holder.contains_directory(Path(path)):
            raise StorageUnavailableError('scratch directory is outside the verified volume')

    def close(self):
        if self._holder is not None:
            holder, self._holder = self._holder, None
            holder.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
