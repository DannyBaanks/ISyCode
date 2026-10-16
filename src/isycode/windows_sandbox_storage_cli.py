"""Explicit operator inspection/registration; never mounts or formats storage."""
import argparse
from dataclasses import asdict, fields
import json
import os
from pathlib import Path
import sys
import tempfile

from isycode.platform_windows_sandbox_volume import (
    StorageConfig, StorageIdentity, StorageUnavailableError, VolumeObservation,
    MAX_STORAGE_BYTES, validate_config, validate_observation,
)

SCHEMA = 'isycode.windows-bounded-storage/1'
CONFIG_ENV = 'ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG'


def inspect_volume(config):
    from isycode.platform_windows_sandbox_volume_api import inspect_volume as probe
    return probe(config)


def load_storage_config(path):
    from isycode.platform_windows_storage import WindowsStorage
    from isycode.winfs import is_link
    storage = WindowsStorage()
    fd = None
    try:
        path = Path(path)
        if any(is_link(p) for p in (path, *path.parents)):
            raise StorageUnavailableError('storage configuration cannot contain links')
        fd = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        info = os.fstat(fd)
        named = path.stat()
        if (info.st_nlink != 1 or not storage.private(path, fd=fd)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino) or info.st_size > 65536):
            raise StorageUnavailableError('storage configuration is not private and independent')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise StorageUnavailableError('storage configuration exceeds its size limit')
            record = json.loads(raw)
        if (not isinstance(record, dict) or set(record) != {'schema', 'volume_guid', 'backing_file', 'max_bytes', 'identity'}
                or record['schema'] != SCHEMA or not isinstance(record['backing_file'], str)
                or not isinstance(record['identity'], dict)
                or set(record['identity']) != {field.name for field in fields(StorageIdentity)}):
            raise StorageUnavailableError('unknown storage configuration schema')
        expected = StorageIdentity(**record['identity'])
        config = StorageConfig(record['volume_guid'], Path(record['backing_file']), record['max_bytes'], expected)
        validate_observation(config, VolumeObservation(expected, 'NTFS', 2, True, True, True, True))
        return config
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise StorageUnavailableError('storage configuration is missing, malformed or unsafe') from exc
    finally:
        if fd is not None:
            os.close(fd)


def register_storage_config(config, destination):
    import win32file
    from isycode.platform_windows_storage import WindowsStorage
    from isycode.winfs import is_link
    validate_config(config)
    identity = validate_observation(config, inspect_volume(config))
    destination = Path(destination)
    storage = WindowsStorage()
    if not destination.parent.exists():
        storage.ensure_directory(destination.parent)
    if not storage.private(destination.parent) or is_link(destination):
        raise StorageUnavailableError('configuration parent must already be private')
    if destination.exists():
        current = load_storage_config(destination)
        if (current.volume_guid.casefold() != config.volume_guid.casefold()
                or current.backing_file != config.backing_file or current.registered_identity != identity):
            raise StorageUnavailableError('different existing configuration is never overwritten')
        return identity
    fd, name = tempfile.mkstemp(prefix='.isycode-storage-', dir=destination.parent)
    temporary = Path(name)
    try:
        storage.protect(temporary)
        record = {'schema': SCHEMA, 'volume_guid': config.volume_guid, 'backing_file': str(config.backing_file),
                  'max_bytes': MAX_STORAGE_BYTES, 'identity': asdict(identity)}
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write((json.dumps(record, sort_keys=True) + '\n').encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        # No REPLACE_EXISTING: a concurrent registration cannot overwrite data.
        win32file.MoveFileEx(str(temporary), str(destination), win32file.MOVEFILE_WRITE_THROUGH)
        if load_storage_config(destination).registered_identity != identity:
            raise StorageUnavailableError('storage configuration readback changed')
        return identity
    finally:
        if fd is not None:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def configured_storage():
    selected = os.environ.get(CONFIG_ENV)
    if not selected:
        raise StorageUnavailableError('select an operator-registered bounded storage configuration')
    return load_storage_config(Path(selected))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect-image', 'inspect-volume', 'register'):
        option = commands.add_parser(command)
        option.add_argument('--image', type=Path, required=True)
        if command != 'inspect-image':
            option.add_argument('--volume-guid', required=True)
        if command == 'register':
            option.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('Windows native storage inspection is unavailable on this platform', file=sys.stderr)
        return 1
    try:
        if args.command == 'inspect-image':
            from isycode.platform_windows_sandbox_volume_api import inspect_image
            result = inspect_image(args.image)
        else:
            config = StorageConfig(args.volume_guid, args.image)
            result = (register_storage_config(config, args.config) if args.command == 'register'
                      else validate_observation(config, inspect_volume(config)))
        print(json.dumps(asdict(result), indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
