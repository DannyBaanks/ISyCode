"""Recover only an explicitly named, owned, stale native scratch allocation."""
from datetime import timezone
import json
import os
from pathlib import Path
import re

import shutil
import tempfile

import pywintypes
import win32api
import win32con
import win32process
import win32security as security
import win32event

from isycode.platform_windows_storage import WindowsStorage
from isycode.winfs import is_link

PROFILE_PREFIX = 'isycode.test.'


def is_owned_profile_name(value) -> bool:
    return (isinstance(value, str)
            and re.fullmatch(re.escape(PROFILE_PREFIX) + r'[a-f0-9]{32}', value) is not None)


def _birth(handle):
    return win32process.GetProcessTimes(handle)['CreationTime'].astimezone(timezone.utc).isoformat()


def write_ownership(root: Path, name: str, sid: bytes, *, phase='ALLOCATED', storage_identity=None):
    storage = WindowsStorage()
    payload = {'schema': 'isycode-native-scratch/1', 'root': str(root),
        'profile': name, 'profile_sid': security.ConvertSidToStringSid(security.SID(sid)),
        'owner_pid': os.getpid(), 'owner_birth': _birth(win32api.GetCurrentProcess()),
        'user_sid': security.ConvertSidToStringSid(storage._user()), 'phase': phase}
    if storage_identity is not None:
        payload.update(schema='isycode-native-scratch/2',
                       storage_provider='windows-fixed-vhd/1', storage_identity=storage_identity.payload())
    path = root / 'ownership.json'
    fd, temporary = tempfile.mkstemp(prefix='.ownership-', dir=root)
    temporary = Path(temporary)
    try:
        storage.protect(temporary)
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(json.dumps(payload, sort_keys=True).encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        storage.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def erase_data(root: Path, *, keep_ownership: bool):
    if not keep_ownership:
        shutil.rmtree(root)
        return
    failures = []
    for item in root.iterdir():
        if item.name == 'ownership.json':
            continue
        try:
            if is_link(item):
                item.rmdir() if item.is_dir() else item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise OSError('some owned scratch data could not be erased') from failures[0]


def recover_owned_scratch(root: Path, *, storage_config=None) -> str:
    return _recover_with_storage(root, storage_config)


def _recover_with_storage(root, storage_config):
    # Inspect only a private record at the exact historical boundary. Bind the
    # provider before the existing recovery path can delete any profile/data.
    if root.parent != Path(root.anchor) or not re.fullmatch(r'isycode-lpac-[a-z0-9_]{8}', root.name):
        raise ValueError('scratch ownership boundary is invalid')
    if not root.exists():
        return 'ABSENT'
    if is_link(root) or not WindowsStorage().private(root / 'ownership.json'):
        raise ValueError('scratch ownership record is unsafe')
    payload = json.loads((root / 'ownership.json').read_text(encoding='utf-8'))
    if payload.get('schema') == 'isycode-native-scratch/2':
        if storage_config is None:
            raise ValueError('schema2 recovery requires storage configuration')
        if payload.get('storage_provider') != 'windows-fixed-vhd/1':
            raise ValueError('scratch storage provider does not match')
        from isycode.platform_windows_sandbox_volume import BoundedStorageProvider, StorageIdentity
        try:
            expected = StorageIdentity(**payload['storage_identity'])
        except (KeyError, TypeError) as exc:
            raise ValueError('scratch storage identity is invalid') from exc
        with BoundedStorageProvider(storage_config).open(expected) as lease:
            lease.assert_directory(root)
            return _recover_owned_scratch(root, payload)
    if str(root.anchor).casefold().startswith('\\\\?\\volume{'):
        raise ValueError('volume scratch requires schema2 ownership')
    return _recover_owned_scratch(root, payload)


def _recover_owned_scratch(root: Path, payload) -> str:
    from isycode.platform_windows_sandbox_resources import userenv, advapi
    import ctypes as c
    from ctypes import wintypes as w
    storage = WindowsStorage()
    # Exact directory requested; no sweeping deletion of prefix matches.
    if root.parent != Path(root.anchor) or not re.fullmatch(r'isycode-lpac-[a-z0-9_]{8}', root.name):
        raise ValueError('scratch ownership boundary is invalid')
    if not root.exists():
        return 'ABSENT'
    if is_link(root) or not storage.private(root / 'ownership.json'):
        raise ValueError('scratch ownership record is unsafe')
    user = security.ConvertSidToStringSid(storage._user())
    if (payload.get('schema') not in {'isycode-native-scratch/1', 'isycode-native-scratch/2'} or payload.get('root') != str(root)
            or payload.get('user_sid') != user
            or not is_owned_profile_name(payload.get('profile', ''))):
        raise ValueError('scratch ownership record does not match')
    descriptor = security.GetNamedSecurityInfo(str(root), security.SE_FILE_OBJECT,
        security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    if security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) != user:
        raise ValueError('scratch ownership changed')
    allowed = {user, 'S-1-5-18', payload['profile_sid']}
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise ValueError('scratch ownership ACL is unsafe')
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] != security.ACCESS_ALLOWED_ACE_TYPE or security.ConvertSidToStringSid(ace[2]) not in allowed:
            raise ValueError('scratch ownership ACL changed')
    try:
        owner = win32api.OpenProcess(0x1000 | win32con.SYNCHRONIZE, False, int(payload['owner_pid']))
    except pywintypes.error as exc:
        if exc.winerror != 87:
            return 'ACTIVE_OR_UNVERIFIABLE'
    else:
        try:
            if (win32event.WaitForSingleObject(owner, 0) == win32event.WAIT_TIMEOUT
                    and _birth(owner) == payload['owner_birth']):
                return 'ACTIVE'
        finally:
            owner.Close()
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes, derive.restype = [w.LPCWSTR, c.POINTER(c.c_void_p)], c.c_long
    pointer = c.c_void_p()
    hr = derive(payload['profile'], c.byref(pointer))
    if hr < 0:
        raise OSError(hr, 'scratch profile identity cannot be verified')
    try:
        sid = c.string_at(pointer, advapi.GetLengthSid(pointer))
        if security.ConvertSidToStringSid(security.SID(sid)) != payload['profile_sid']:
            raise ValueError('scratch ownership profile SID changed')
    finally:
        advapi.FreeSid(pointer)
    hr = userenv.DeleteAppContainerProfile(payload['profile'])
    if hr < 0 and (hr & 0xFFFFFFFF) not in {0x80070002, 0x80070490}:
        try:
            erase_data(root, keep_ownership=True)
        finally:
            raise OSError(hr, 'stale profile cleanup failed; ownership record retained')
    erase_data(root, keep_ownership=False)
    return 'RECOVERED'
