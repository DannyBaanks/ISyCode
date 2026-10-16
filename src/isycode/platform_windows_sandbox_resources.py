"""Private runtime, stage and owned profile ACLs; no unrelated host ACL changes."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import secrets
import shutil
import stat
import hashlib

import win32security as security

from isycode.platform_windows_storage import WindowsStorage
from isycode.winfs import is_link
from isycode.sensitive_paths import is_sensitive_path_name
from isycode.platform_windows_sandbox_recovery import PROFILE_PREFIX, write_ownership, erase_data


userenv = c.WinDLL('userenv', use_last_error=True)
userenv.CreateAppContainerProfile.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR,
    c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
userenv.CreateAppContainerProfile.restype = c.c_long
userenv.DeleteAppContainerProfile.argtypes = [w.LPCWSTR]
userenv.DeleteAppContainerProfile.restype = c.c_long
advapi = c.WinDLL('advapi32')
advapi.GetLengthSid.argtypes = [c.c_void_p]
advapi.GetLengthSid.restype = w.DWORD
advapi.FreeSid.argtypes = [c.c_void_p]
advapi.FreeSid.restype = c.c_void_p


def _profile_sid(name):
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes, derive.restype = [w.LPCWSTR, c.POINTER(c.c_void_p)], c.c_long
    pointer = c.c_void_p()
    hr = derive(name, c.byref(pointer))
    if hr < 0:
        raise OSError(hr, 'profile identity could not be derived')
    try:
        return c.string_at(pointer, advapi.GetLengthSid(pointer))
    finally:
        advapi.FreeSid(pointer)


def _profile_folder(sid: str, name: str | None = None) -> Path:
    """Discover only the freshly-created profile; never infer a host path."""
    get_folder = userenv.GetAppContainerFolderPath
    get_folder.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
    get_folder.restype = c.c_long
    pointer = c.c_void_p()
    hr = get_folder(sid, c.byref(pointer))
    if hr < 0:
        raise OSError(hr, 'profile storage could not be discovered')
    free = c.WinDLL('ole32').CoTaskMemFree
    free.argtypes, free.restype = [c.c_void_p], None
    try:
        folder = Path(c.wstring_at(pointer))
    finally:
        free(pointer)
    if ((name is not None and folder.parent.name != name)
            or any(is_link(p) for p in (folder, *folder.parents))):
        raise ValueError('profile storage does not match the owned profile')
    return folder.parent


def _registry_read_sid() -> bytes:
    kernel = c.WinDLL('kernelbase', use_last_error=True)
    derive = kernel.DeriveCapabilitySidsFromName
    derive.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p), c.POINTER(w.DWORD),
                       c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    derive.restype = w.BOOL
    free = c.WinDLL('kernel32').LocalFree
    free.argtypes, free.restype = [c.c_void_p], c.c_void_p
    groups, capabilities = c.c_void_p(), c.c_void_p()
    group_count, capability_count = w.DWORD(), w.DWORD()
    if not derive('registryRead', c.byref(groups), c.byref(group_count),
                  c.byref(capabilities), c.byref(capability_count)):
        raise c.WinError(c.get_last_error())
    try:
        if capability_count.value != 1:
            raise ValueError('unexpected registryRead capability result')
        pointer = c.c_void_p.from_address(capabilities.value).value
        return c.string_at(pointer, advapi.GetLengthSid(pointer))
    finally:
        for array, count in ((groups, group_count), (capabilities, capability_count)):
            if array.value:
                for index in range(count.value):
                    free(c.c_void_p.from_address(array.value + index * c.sizeof(c.c_void_p)).value)
                free(array)


def runtime_files(runtime: Path):
    """The exact bounded, link-free CPython inputs used by identity and copy."""
    if any(is_link(part) for part in (runtime, *runtime.parents)):
        raise ValueError('unsafe runtime root')
    selected = []
    for path in runtime.iterdir():
        # The sandbox runs the exact CPython interpreter, not optional
        # launchers such as python3.exe. Windows Python installs may ship that
        # alias as a non-regular app-execution shim, so copying every root EXE
        # would reject an otherwise valid runtime or stage an unused launcher.
        if path.name.casefold() == 'python.exe' or path.suffix.lower() == '.dll':
            selected.append(path)
    for subtree in (runtime / 'Lib', runtime / 'DLLs'):
        if is_link(subtree):
            raise ValueError('reparse point in runtime')
        if not subtree.exists():
            continue
        for folder, dirs, files in os.walk(subtree, followlinks=False):
            dirs[:] = [name for name in dirs if name not in {
                'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter'}]
            for name in dirs:
                if is_link(Path(folder) / name):
                    raise ValueError('reparse point in runtime')
            selected.extend(Path(folder) / name for name in files)
    total = 0
    result = []
    for path in sorted(selected):
        if is_link(path) or not path.is_file():
            raise ValueError(
                'runtime input is not a regular file: '
                + path.relative_to(runtime).as_posix())
        total += path.stat().st_size
        if total > 512 * 1024 ** 2:
            raise ValueError('runtime exceeds the copying budget')
        result.append((path.relative_to(runtime).as_posix(), path))
    return tuple(result)


class WindowsSandboxResources:
    @classmethod
    def prepare(cls, staging: Path, runtime: Path, masks: tuple[tuple[str, bool], ...],
                expected_runtime_digest: str | None = None, *, storage_lease=None):
        # Initial acceptance runtime is a private copy of CPython, not arbitrary
        # PATH binaries. The backend is not exposed to product execution yet.
        for root in (staging, runtime):
            if any(is_link(p) for p in (root, *root.parents)):
                raise ValueError('sandbox roots cannot contain reparse points')
        if not (runtime / 'python.exe').is_file() or not (runtime / 'Lib/os.py').is_file():
            raise ValueError('runtime must be a complete CPython installation')
        if storage_lease is not None:
            storage_lease.assert_unchanged()
        allocation_root = staging.anchor if storage_lease is None else storage_lease.root
        staging_bytes = cls._check_tree(staging)
        inputs = runtime_files(runtime)
        required_bytes = staging_bytes + sum(path.stat().st_size for _, path in inputs)
        if shutil.disk_usage(allocation_root).free < required_bytes + 64 * 1024 ** 2:
            raise OSError('insufficient free space for private sandbox copies')
        self = cls()
        self.profile_name = PROFILE_PREFIX + secrets.token_hex(16)
        self.storage_lease = storage_lease
        # LPAC cannot traverse the user's private Temp ancestors. Allocate a
        # private directory on the same volume, without changing parent ACLs.
        # Create it with the protected owner/SYSTEM DACL from the first
        # filesystem operation: mkdtemp inherits the volume-root ACL on some
        # hosted Windows runners, which may be shared with other principals.
        self.scratch_root = Path(allocation_root) / ('isycode-lpac-' + secrets.token_hex(16))
        self.runtime_root = self.scratch_root / 'runtime'
        self.stage_root = self.scratch_root / 'workspace'
        self.profile_created = False
        try:
            storage = WindowsStorage()
            if storage_lease is not None:
                storage_lease.assert_directory(self.scratch_root)
            storage.ensure_directory(self.scratch_root)
            self.profile_sid = _profile_sid(self.profile_name)
            record_options = {} if storage_lease is None else {'storage_identity': storage_lease.identity}
            write_ownership(self.scratch_root, self.profile_name, self.profile_sid,
                            phase='ALLOCATED', **record_options)
            self.runtime_root.mkdir()
            shutil.copytree(staging, self.stage_root)
            for relative, directory in masks:
                parts = relative.split('/')
                if any(part in {'', '.', '..'} or ':' in part or '\\' in part for part in parts):
                    raise ValueError('invalid sensitive mask')
                target = self.stage_root.joinpath(*parts)
                if target.exists():
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
            for folder, dirs, files in os.walk(self.stage_root):
                if any(is_sensitive_path_name(name) for name in (*dirs, *files)):
                    raise ValueError('unreviewed sensitive entry in staging')
            digest = hashlib.sha256()
            for relative, item in inputs:
                destination = self.runtime_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, destination)
                digest.update(relative.encode('utf-8') + b'\0')
                digest.update(hashlib.sha256(destination.read_bytes()).digest())
            self.runtime_digest = digest.hexdigest()
            if expected_runtime_digest is not None and self.runtime_digest != expected_runtime_digest:
                raise ValueError('runtime changed after approval')
            # Runtime bytes remain intact. registryRead is needed by Windows
            # activation contexts, Winsock initialization and CreateProcess;
            # it does not grant network capabilities or override registry DACLs.
            self.capability_sids = (_registry_read_sid(),)
            sid_ptr = c.c_void_p()
            hr = userenv.CreateAppContainerProfile(self.profile_name, self.profile_name,
                'Temporary ISyCode isolation control', None, 0, c.byref(sid_ptr))
            if hr < 0:
                raise OSError(hr, 'CreateAppContainerProfile failed')
            self.profile_created = True
            try:
                created_sid = c.string_at(sid_ptr, advapi.GetLengthSid(sid_ptr))
                if created_sid != self.profile_sid:
                    raise ValueError('created profile identity did not match allocation')
            finally:
                advapi.FreeSid(sid_ptr)
            write_ownership(self.scratch_root, self.profile_name, self.profile_sid,
                            phase='PROFILE_CREATED', **record_options)
            sid = security.ConvertSidToStringSid(security.SID(self.profile_sid))
            user = security.ConvertSidToStringSid(storage._user())
            # CreateAppContainerProfile adds a writable root outside scratch.
            # Lock the entire owned package directory, not only AC/Temp: a
            # writable parent could replace or rename read-only descendants.
            self.profile_root = _profile_folder(sid, self.profile_name)
            self._acl_tree(self.profile_root, user, sid, 'GRGX')
            # Only scratch/staging copies receive LPAC access. Traverse-only
            # scratch access does not grant write access to the runtime.
            self._acl(self.scratch_root, user, sid, 'GRGX')
            self._acl_tree(self.runtime_root, user, sid, 'GRGX')
            self._acl_tree(self.stage_root, user, sid, '0x1301bf')
            for marker in self.stage_root.rglob('.isyroot'):
                self._acl(marker, user, sid, 'GR')
                parent = marker.parent
                while parent == self.stage_root or self.stage_root in parent.parents:
                    self._acl(parent, user, sid, '0x1201bf')
                    if parent == self.stage_root:
                        break
                    parent = parent.parent
            temp = self.scratch_root / 'temp'
            temp.mkdir()
            self._acl_tree(temp, user, sid, '0x1301bf')
            self.environment = {'SystemRoot': os.environ['SystemRoot'],
                'TEMP': str(temp), 'TMP': str(temp), 'PATH': str(self.runtime_root),
                'LOCALAPPDATA': str(temp), 'PYTHONUTF8': '1'}
            return self
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check_tree(root):
        total = 0
        for folder, dirs, files in os.walk(root, followlinks=False):
            for name in (*dirs, *files):
                path = Path(folder) / name
                if is_link(path):
                    raise ValueError('reparse point in sandbox source')
                if path.is_file() and path.stat().st_nlink != 1:
                    raise ValueError('hardlink in sandbox source')
                if path.is_file():
                    total += path.stat().st_size
                    if total > 512 * 1024 ** 2:
                        raise ValueError('staging exceeds the copying budget')
        return total

    @staticmethod
    def _acl(path, user, sid, access):
        inheritance = 'OICI' if path.is_dir() else ''
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f'O:{user}D:P(A;{inheritance};FA;;;{user})(A;{inheritance};FA;;;SY)'
            f'(A;{inheritance};{access};;;{sid})S:(ML;{inheritance};NW;;;LW)', security.SDDL_REVISION_1)
        security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION
            | security.LABEL_SECURITY_INFORMATION, None, None,
            descriptor.GetSecurityDescriptorDacl(), descriptor.GetSecurityDescriptorSacl())

    @classmethod
    def _acl_tree(cls, root, user, sid, access):
        cls._acl(root, user, sid, access)
        for folder, dirs, files in os.walk(root, followlinks=False):
            for name in (*dirs, *files):
                path = Path(folder) / name
                if is_link(path):
                    raise ValueError('reparse point in sandbox copy')
                cls._acl(path, user, sid, access)

    def close(self):
        failure = None
        if self.profile_created:
            hr = userenv.DeleteAppContainerProfile(self.profile_name)
            if hr < 0:
                failure = OSError(hr, 'DeleteAppContainerProfile failed; ownership record retained')
            else:
                self.profile_created = False
        try:
            if self.storage_lease is not None:
                self.storage_lease.assert_directory(self.scratch_root)
            if self.scratch_root.exists():
                erase_data(self.scratch_root, keep_ownership=failure is not None)
        except OSError as exc:
            if failure is None:
                failure = exc
        if failure is not None:
            raise failure

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
