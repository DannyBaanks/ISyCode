"""Restrict only the suspended child's own AppContainer registry storage."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import winreg

import pywintypes
import win32api
import win32con
import win32security as security

from isycode.platform_windows_sandbox_resources import _profile_folder
from isycode.platform_windows_sandbox_recovery import is_owned_profile_name


def _key_name(handle: int) -> str:
    query = c.WinDLL('ntdll').NtQueryKey
    query.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)]
    query.restype = c.c_long
    size = w.ULONG()
    # KeyNameInformation (3) returns the name of this already-open key.
    query(handle, 3, None, 0, c.byref(size))
    if not 4 < size.value <= 65536:
        raise OSError('profile registry identity could not be measured')
    buffer = c.create_string_buffer(size.value)
    if query(handle, 3, buffer, size.value, c.byref(size)) < 0:
        raise OSError('profile registry identity could not be read')
    length = w.ULONG.from_buffer(buffer).value
    if length > len(buffer) - 4 or length % 2:
        raise OSError('invalid profile registry identity')
    # Impersonation must not trigger Python's lazy codec imports from host Lib.
    return c.wstring_at(c.addressof(buffer) + 4, length // c.sizeof(c.c_wchar))


def restrict_profile_registry(process, profile_sid: bytes) -> None:
    """Look up under the child's identity, restore caller, then protect the key.

    No child code runs and no credentials or privileged token are acquired.
    Existing caller impersonation is refused instead of silently discarded.
    """
    try:
        prior = security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
    except pywintypes.error as exc:
        if exc.winerror != 1008:  # ERROR_NO_TOKEN
            raise
    else:
        prior.Close()
        raise OSError('sandbox launch cannot replace existing thread impersonation')
    token = security.OpenProcessToken(process, win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE)
    try:
        user = security.GetTokenInformation(token, security.TokenUser)[0]
        user_sid = security.ConvertSidToStringSid(user)
        # GetTokenInformation(TokenAppContainerSid) binds discovery to the
        # exact SID supplied at creation, not a caller-controlled registry path.
        get_info = c.WinDLL('advapi32', use_last_error=True).GetTokenInformation
        get_info.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        get_info.restype = w.BOOL
        needed = w.DWORD()
        get_info(int(token), 31, None, 0, c.byref(needed))
        if c.get_last_error() != 122 or not c.sizeof(c.c_void_p) <= needed.value <= 65536:
            raise OSError('profile token identity could not be measured')
        buffer = c.create_string_buffer(needed.value)
        if not get_info(int(token), 31, buffer, len(buffer), c.byref(needed)):
            raise c.WinError(c.get_last_error())
        actual = c.c_void_p.from_buffer(buffer)
        get_length = c.WinDLL('advapi32').GetLengthSid
        get_length.argtypes, get_length.restype = [c.c_void_p], w.DWORD
        if not actual.value or c.string_at(actual, get_length(actual)) != profile_sid:
            raise OSError('registry token does not match the sandbox profile')
        sid = security.ConvertSidToStringSid(security.SID(profile_sid))
        profile_root = _profile_folder(sid)
        if not is_owned_profile_name(profile_root.name):
            raise OSError('profile is outside the owned sandbox namespace')
        key = c.c_void_p()
        api = c.WinDLL('userenv').GetAppContainerRegistryLocation
        api.argtypes, api.restype = [w.DWORD, c.POINTER(c.c_void_p)], c.c_long
        security.ImpersonateLoggedOnUser(token)
        try:
            hr = api(winreg.KEY_READ, c.byref(key))
            if hr < 0:
                raise OSError(hr, 'profile registry could not be discovered')
            try:
                name = _key_name(key.value)
            finally:
                winreg.CloseKey(key.value)
        finally:
            security.RevertToSelf()
    finally:
        token.Close()
    # These are the native registry's API namespace and current token identity,
    # not an installation path or a guessed AppContainer registry layout.
    prefix = '\\REGISTRY\\USER\\'
    if not name.casefold().startswith(prefix.casefold()):
        raise OSError(f'profile registry is outside the current-user namespace: {name!r}')
    relative = name[len(prefix):]
    parts = relative.split('\\')
    if parts[0].casefold() not in {user_sid.casefold(), (user_sid + '_Classes').casefold()}:
        raise OSError(f'profile registry is outside the owned profile: {name!r}')
    # Windows names registry storage by the profile moniker, not its SID.
    # Bind that name to the SID using the independently discovered folder.
    if parts[-1].casefold() != profile_root.name.casefold():
        raise OSError('profile registry does not match the discovered moniker')
    descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f'D:P(A;CI;KA;;;{user_sid})(A;CI;KA;;;SY)(A;CI;KR;;;{sid})', 1)
    with winreg.OpenKey(winreg.HKEY_USERS, relative, 0, winreg.KEY_ALL_ACCESS) as root:
        owner = security.GetSecurityInfo(int(root), security.SE_REGISTRY_KEY,
                                        security.OWNER_SECURITY_INFORMATION).GetSecurityDescriptorOwner()
        if security.ConvertSidToStringSid(owner) != user_sid:
            raise OSError('profile registry is not owned by the sandbox user')
        _protect_tree(root, descriptor)


def _protect_tree(key, descriptor):
    index = 0
    while True:
        try:
            name = winreg.EnumKey(key, index)
        except OSError as exc:
            if exc.winerror != 259:  # ERROR_NO_MORE_ITEMS
                raise
            break
        with winreg.OpenKey(key, name, 0, winreg.KEY_ALL_ACCESS) as child:
            _protect_tree(child, descriptor)
        index += 1
    security.SetSecurityInfo(int(key), security.SE_REGISTRY_KEY,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)
