"""Read-only Win32/VirtDisk queries. No attach, format, resize or elevation."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import uuid
import re
import win32file
import win32security as security
import pywintypes

from isycode.platform_windows_storage import WindowsStorage
from isycode.winfs import is_link
from isycode.platform_windows_sandbox_volume import (
    StorageUnavailableError, StorageIdentity, VolumeObservation, ImageObservation,
    MAX_STORAGE_BYTES, validate_config,
)


class GUID(c.Structure):
    _fields_ = [('a', w.DWORD), ('b', w.WORD), ('d', w.WORD), ('tail', c.c_ubyte * 8)]


class VIRTUAL_STORAGE_TYPE(c.Structure):
    _fields_ = [('DeviceId', w.DWORD), ('VendorId', GUID)]


class DEPENDENCY_ENTRY(c.Structure):
    _fields_ = [('flags', w.DWORD), ('provider_flags', w.DWORD),
        ('storage', VIRTUAL_STORAGE_TYPE), ('ancestor', w.DWORD),
        ('device', c.c_void_p), ('host', c.c_void_p), ('dependent', c.c_void_p), ('relative', c.c_void_p)]


class DISK_SIZE(c.Structure):
    _fields_ = [('virtual', c.c_ulonglong), ('physical', c.c_ulonglong),
                ('block', w.DWORD), ('sector', w.DWORD)]


class INFO_DATA(c.Union):
    _fields_ = [('size', DISK_SIZE), ('identifier', GUID), ('storage', VIRTUAL_STORAGE_TYPE),
                ('subtype', w.DWORD), ('loaded', w.BOOL)]


class DISK_INFO(c.Structure):
    _fields_ = [('version', w.DWORD), ('data', INFO_DATA)]


class OPEN_PARAMETERS(c.Structure):
    _fields_ = [('version', w.DWORD), ('depth', w.DWORD)]


kernel = c.WinDLL('kernel32', use_last_error=True)
virtual = c.WinDLL('virtdisk')
_MICROSOFT = uuid.UUID('ec984aec-a0f9-47e9-901f-71415a66345b')


def _bind(dll, name, args, result=w.DWORD):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


_dependencies = _bind(virtual, 'GetStorageDependencyInformation',
    [w.HANDLE, w.DWORD, w.ULONG, c.c_void_p, c.POINTER(w.ULONG)])
_open_disk = _bind(virtual, 'OpenVirtualDisk', [c.POINTER(VIRTUAL_STORAGE_TYPE), w.LPCWSTR,
    w.DWORD, w.DWORD, c.POINTER(OPEN_PARAMETERS), c.POINTER(w.HANDLE)])
_disk_info = _bind(virtual, 'GetVirtualDiskInformation',
    [w.HANDLE, c.POINTER(w.ULONG), c.POINTER(DISK_INFO), c.POINTER(w.ULONG)])
_physical_path = _bind(virtual, 'GetVirtualDiskPhysicalPath',
    [w.HANDLE, c.POINTER(w.ULONG), w.LPWSTR])
_volume_name = _bind(kernel, 'GetVolumeNameForVolumeMountPointW', [w.LPCWSTR, w.LPWSTR, w.DWORD], w.BOOL)
_volume_info = _bind(kernel, 'GetVolumeInformationW', [w.LPCWSTR, w.LPWSTR, w.DWORD,
    c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL)
_space = _bind(kernel, 'GetDiskFreeSpaceExW', [w.LPCWSTR, c.POINTER(c.c_ulonglong),
    c.POINTER(c.c_ulonglong), c.POINTER(c.c_ulonglong)], w.BOOL)
_drive_type = _bind(kernel, 'GetDriveTypeW', [w.LPCWSTR])
_volume_path = _bind(kernel, 'GetVolumePathNameW', [w.LPCWSTR, w.LPWSTR, w.DWORD], w.BOOL)


def _check(status, what):
    if status:
        raise StorageUnavailableError(status, f'{what} could not be verified')


def _release(handles=(), fd=None):
    failure = None
    for handle in handles:
        if handle is not None:
            try:
                handle.Close()
            except BaseException as exc:
                failure = failure or exc
    if fd is not None:
        try:
            os.close(fd)
        except BaseException as exc:
            failure = failure or exc
    if failure is not None:
        raise failure


def _release_after_error(error, handles=(), fd=None):
    try:
        _release(handles, fd)
    except BaseException as cleanup:
        error.add_note(f'Additional native handle cleanup failure: {cleanup}')


def _string(pointer, buffer, used=None):
    bound = len(buffer) if used is None else used
    start, end = c.addressof(buffer), c.addressof(buffer) + bound
    if not pointer or pointer < start or pointer >= end or pointer % 2:
        raise StorageUnavailableError('invalid dependency string pointer')
    raw = buffer.raw[pointer - start:bound]
    for index in range(0, len(raw) - 1, 2):
        if raw[index:index + 2] == b'\0\0':
            return raw[:index].decode('utf-16-le')
    raise StorageUnavailableError('unterminated dependency string')


def dependencies(handle):
    buffer = c.create_string_buffer(1024 * 1024)
    w.DWORD.from_buffer(buffer).value = 2
    used = w.ULONG()
    _check(_dependencies(int(handle), 1, len(buffer), buffer, c.byref(used)), 'volume dependency')
    count = w.DWORD.from_buffer(buffer, 4).value
    if count != 1 or not 8 + c.sizeof(DEPENDENCY_ENTRY) <= used.value <= len(buffer):
        raise StorageUnavailableError('volume is not a single direct VHD dependency')
    entry = DEPENDENCY_ENTRY.from_buffer(buffer, 8)
    if (entry.storage.DeviceId != 2 or entry.ancestor != 0 or entry.flags & (1 | 8 | 256 | 512)
            or uuid.UUID(bytes_le=c.string_at(c.byref(entry.storage.VendorId), 16)) != _MICROSOFT):
        raise StorageUnavailableError('unsupported or remote VHD dependency')
    return (_string(entry.host, buffer, used.value), _string(entry.relative, buffer, used.value),
            _string(entry.device, buffer, used.value))


def same_physical_device(first, second):
    pattern = r'\\\\\.\\PhysicalDrive[0-9]+'
    return bool(isinstance(first, str) and isinstance(second, str)
                and re.fullmatch(pattern, first, re.IGNORECASE)
                and re.fullmatch(pattern, second, re.IGNORECASE)
                and first.casefold() == second.casefold())


class PinnedDisk:
    """Pin path ancestors across both opens and the full provider lease."""
    def __init__(self, disk, parents):
        self.disk, self.parents = disk, parents

    def __int__(self):
        return int(self.disk)

    def Close(self):
        handles, self.parents = [self.disk, *self.parents], []
        self.disk = None
        _release(handles)


def _guid(value):
    return str(uuid.UUID(bytes_le=c.string_at(c.byref(value), 16)))


def _query_disk(handle, version):
    info = DISK_INFO(version)
    size, used = w.ULONG(c.sizeof(info)), w.ULONG()
    _check(_disk_info(int(handle), c.byref(size), c.byref(info), c.byref(used)), 'VHD information')
    minimum = DISK_INFO.data.offset + {1: c.sizeof(DISK_SIZE), 2: c.sizeof(GUID),
                                     6: c.sizeof(VIRTUAL_STORAGE_TYPE), 7: 4, 13: 4}[version]
    if (size.value > c.sizeof(info) or used.value > c.sizeof(info)
            or size.value < minimum or used.value < minimum):
        raise StorageUnavailableError('VHD information exceeds its SDK layout')
    return info.data


def _open_image(path):
    path = Path(path)
    if (not path.is_absolute() or str(path).startswith('\\\\')
            or any(is_link(p) for p in (path, *path.parents))):
        raise StorageUnavailableError('backing image must be an explicit local regular file')
    fd = disk = None
    parents = []
    try:
        for parent in reversed(path.parents):
            handle = win32file.CreateFile(str(parent), 0x80, 3, None, 3,
                                          0x02000000 | 0x00200000, None)
            parents.append(handle)
            if is_link(parent):
                raise StorageUnavailableError('backing ancestor became a reparse point')
        fd = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        if is_link(path):
            raise StorageUnavailableError('backing image became a reparse point')
        if os.fstat(fd).st_nlink != 1 or not path.is_file():
            raise StorageUnavailableError('backing image is not an independent regular file')
        storage = VIRTUAL_STORAGE_TYPE(2, GUID.from_buffer_copy(_MICROSOFT.bytes_le))
        out = w.HANDLE()
        params = OPEN_PARAMETERS(1, 1)
        _check(_open_disk(c.byref(storage), str(path), 0x80000, 0,
                          c.byref(params), c.byref(out)), 'VHD open for information')
        import pywintypes
        disk = pywintypes.HANDLE(out.value)
        return fd, PinnedDisk(disk, parents)
    except BaseException as exc:
        _release_after_error(exc, (disk, *parents), fd)
        raise


def _file_id(fd):
    info = os.fstat(fd)
    return f'{info.st_dev:x}:{info.st_ino:x}'


def _image_info(fd, disk):
    identifier = _guid(_query_disk(disk, 2).identifier)
    storage = _query_disk(disk, 6).storage
    if uuid.UUID(bytes_le=c.string_at(c.byref(storage.VendorId), 16)) != _MICROSOFT:
        raise StorageUnavailableError('VHD provider is not the verified Microsoft provider')
    fixed = _query_disk(disk, 7).subtype == 2
    size = _query_disk(disk, 1).size.virtual
    path = None
    if _query_disk(disk, 13).loaded:
        buffer = c.create_unicode_buffer(32768)
        length = w.ULONG(c.sizeof(buffer))
        _check(_physical_path(int(disk), c.byref(length), buffer), 'attached physical device')
        if length.value > c.sizeof(buffer):
            raise StorageUnavailableError('physical device path is truncated')
        path = buffer.value
    return ImageObservation(identifier, storage.DeviceId, fixed, size, path, _file_id(fd))


def inspect_image(path):
    try:
        fd, disk = _open_image(path)
    except (OSError, pywintypes.error, ValueError) as exc:
        raise StorageUnavailableError('backing image cannot be inspected') from exc
    try:
        return _image_info(fd, disk)
    finally:
        _release((disk,), fd)


def _private_root(handle):
    descriptor = security.GetSecurityInfo(int(handle), security.SE_FILE_OBJECT,
        security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    user = security.ConvertSidToStringSid(WindowsStorage()._user())
    control, _ = descriptor.GetSecurityDescriptorControl()
    if (not control & security.SE_DACL_PROTECTED
            or security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) != user):
        return False
    acl, access = descriptor.GetSecurityDescriptorDacl(), 0
    if acl is None:
        return False
    for index in range(acl.GetAceCount()):
        (kind, flags), mask, sid = acl.GetAce(index)
        principal = security.ConvertSidToStringSid(sid)
        if kind != security.ACCESS_ALLOWED_ACE_TYPE or principal not in {user, 'S-1-5-18'}:
            return False
        if principal == user and not flags & security.INHERIT_ONLY_ACE:
            access |= mask
    return access & 0x1f01ff == 0x1f01ff


class VolumeHandleSet:
    def __init__(self, config, root_handle, fd, disk):
        self.config, self.root = config, Path(config.volume_guid)
        self.root_handle, self.fd, self.disk = root_handle, fd, disk
        self.observation = self.refresh()

    def refresh(self):
        config = self.config
        resolved = c.create_unicode_buffer(128)
        if not _volume_name(config.volume_guid, resolved, len(resolved)):
            raise StorageUnavailableError(c.get_last_error(), 'volume GUID is unavailable')
        if resolved.value.casefold() != config.volume_guid.casefold() or is_link(self.root):
            raise StorageUnavailableError('volume alias changed')
        filesystem, serial = c.create_unicode_buffer(64), w.DWORD()
        if not _volume_info(config.volume_guid, None, 0, c.byref(serial), None, None, filesystem, len(filesystem)):
            raise StorageUnavailableError(c.get_last_error(), 'filesystem cannot be measured')
        free, total, physical_free = c.c_ulonglong(), c.c_ulonglong(), c.c_ulonglong()
        if not _space(config.volume_guid, c.byref(free), c.byref(total), c.byref(physical_free)):
            raise StorageUnavailableError(c.get_last_error(), 'filesystem capacity is unavailable')
        host, relative, device = dependencies(self.root_handle)
        host = host.rstrip('\\') + '\\'
        if _drive_type(host) != 3:
            raise StorageUnavailableError('image backing volume is not local fixed storage')
        image_path = host.rstrip('\\') + '\\' + relative.lstrip('\\')
        other = os.open(image_path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        try:
            matched = _file_id(other) == _file_id(self.fd)
        finally:
            os.close(other)
        image = _image_info(self.fd, self.disk)
        named = config.backing_file.stat()
        held = os.fstat(self.fd)
        matched = (matched and (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)
                   and same_physical_device(image.physical_device, device)
                   and 0 < image.virtual_bytes <= MAX_STORAGE_BYTES)
        identity = StorageIdentity(config.volume_guid, serial.value, image.image_identifier,
                                   image.backing_file_id, total.value, config.max_bytes)
        return VolumeObservation(identity, filesystem.value, image.device_id, image.fixed, matched,
            _private_root(self.root_handle), WindowsStorage().private(config.backing_file, fd=self.fd))

    def close(self):
        handles, fd = (self.root_handle, self.disk), self.fd
        self.root_handle = self.disk = self.fd = None
        _release(handles, fd)

    def contains_directory(self, path):
        if path.parent != self.root or is_link(path):
            return False
        volume, resolved = c.create_unicode_buffer(32768), c.create_unicode_buffer(128)
        return bool(_volume_path(str(path), volume, len(volume))
                    and _volume_name(volume.value, resolved, len(resolved))
                    and resolved.value.casefold() == self.config.volume_guid.casefold())


def open_volume_handles(config):
    validate_config(config)
    root_handle = disk = None
    fd = None
    try:
        root_handle = win32file.CreateFile(config.volume_guid, 0x20080, 3, None, 3,
                                          0x02000000 | 0x00200000, None)
        fd, disk = _open_image(config.backing_file)
        return VolumeHandleSet(config, root_handle, fd, disk)
    except BaseException as exc:
        _release_after_error(exc, (root_handle, disk), fd)
        if isinstance(exc, (OSError, pywintypes.error, ValueError)):
            raise StorageUnavailableError('volume cannot be inspected as the current user') from exc
        raise


def inspect_volume(config):
    holder = open_volume_handles(config)
    try:
        return holder.observation
    finally:
        holder.close()
