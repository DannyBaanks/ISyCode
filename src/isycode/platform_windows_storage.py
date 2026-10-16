"""Windows locks and protected user/SYSTEM DACLs; no POSIX emulation."""
import errno
import msvcrt
import os
import time
import stat
from pathlib import Path

import win32api
import win32con
import win32file
import win32security as security
import pywintypes

from isycode.winfs import is_link


class WindowsStorage:
    def _real_chain(self, path: Path) -> bool:
        return not any(is_link(part) for part in (path, *path.parents))

    def delete_private(self, path: Path) -> None:
        if is_link(path):
            raise OSError('private artifact cannot be a reparse point')
        if not self.private(path.parent):
            raise ValueError('unsafe private artifact')
        # No sharing allows deletion only when no peer holds the artifact.
        try:
            handle = win32file.CreateFile(str(path), win32con.GENERIC_READ | win32con.DELETE,
                0, None, win32con.OPEN_EXISTING, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
        except pywintypes.error as exc:
            if exc.winerror == 32:
                raise BlockingIOError(errno.EAGAIN, 'private state is in use') from exc
            raise OSError(exc.winerror, str(exc)) from exc
        fd = msvcrt.open_osfhandle(handle.Detach(), os.O_RDONLY | os.O_BINARY)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not self.private(path, fd=fd):
                raise ValueError('unsafe private artifact')
            win32file.SetFileInformationByHandle(msvcrt.get_osfhandle(fd), win32file.FileDispositionInfo, True)
        finally:
            os.close(fd)

    def replace(self, source: Path, destination: Path) -> None:
        try:
            win32file.MoveFileEx(str(source), str(destination),
                win32file.MOVEFILE_REPLACE_EXISTING | win32file.MOVEFILE_WRITE_THROUGH)
        except pywintypes.error as exc:
            raise OSError(exc.winerror, str(exc)) from exc

    def sync_directory(self, path: Path) -> None:
        # CRT cannot open/fsync directories. File fsync + write-through rename
        # is the Windows protocol; no hardware power-loss guarantee is claimed.
        return None

    def _user(self):
        return self._identities()[0]

    def _identities(self):
        token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user = security.GetTokenInformation(token, security.TokenUser)[0]
            default_owner = security.GetTokenInformation(token, security.TokenOwner)
            return user, default_owner
        finally:
            token.Close()

    @staticmethod
    def _private_dacl(acl, user: str) -> bool:
        if acl is None:
            return False
        user_access = 0
        for index in range(acl.GetAceCount()):
            (kind, flags), mask, sid = acl.GetAce(index)
            # Reject unfamiliar/object ACEs and permissions for other principals.
            if kind != security.ACCESS_ALLOWED_ACE_TYPE:
                return False
            principal = security.ConvertSidToStringSid(sid)
            if principal not in {user, 'S-1-5-18'}:
                return False
            if principal == user and not flags & security.INHERIT_ONLY_ACE:
                user_access |= mask
        return user_access & 0x1F01FF == 0x1F01FF

    def _descriptor(self, directory: bool):
        user = security.ConvertSidToStringSid(self._user())
        inherit = 'OICI' if directory else ''
        return security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f'O:{user}D:P(A;{inherit};FA;;;{user})(A;{inherit};FA;;;SY)',
            security.SDDL_REVISION_1)

    def lock(self, fd: int, *, blocking: bool = True) -> None:
        # Lock the same byte even if the caller has already read/appended.
        position = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if not blocking:
                        raise BlockingIOError(errno.EAGAIN, 'private state is in use') from exc
                    time.sleep(0.05)
        finally:
            os.lseek(fd, position, os.SEEK_SET)

    def unlock(self, fd: int) -> None:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.lseek(fd, position, os.SEEK_SET)

    def protect(self, path: Path) -> None:
        if not self._real_chain(path):
            raise ValueError('private state cannot be a reparse point')
        current = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        user, default_owner = self._identities()
        owner = current.GetSecurityDescriptorOwner()
        owner_sid = security.ConvertSidToStringSid(owner)
        user_sid = security.ConvertSidToStringSid(user)
        default_owner_sid = security.ConvertSidToStringSid(default_owner)
        if owner_sid != user_sid:
            if (owner_sid != default_owner_sid
                    or not self._private_dacl(current.GetSecurityDescriptorDacl(), user_sid)):
                raise ValueError('private state is not owned by the current user')
            try:
                security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                    security.OWNER_SECURITY_INFORMATION, user, None, None, None)
            except pywintypes.error as exc:
                raise ValueError('private state owner could not be normalized') from exc
        descriptor = self._descriptor(path.is_dir())
        security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, descriptor.GetSecurityDescriptorDacl(), None)
        if not self.private(path):
            raise ValueError('private state ACL could not be verified')

    def private(self, path: Path, *, fd: int | None = None) -> bool:
        try:
            if not self._real_chain(path):
                return False
            flags = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            descriptor = (security.GetSecurityInfo(msvcrt.get_osfhandle(fd), security.SE_FILE_OBJECT, flags)
                if fd is not None else security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, flags))
            user_sid, default_owner_sid = self._identities()
            user = security.ConvertSidToStringSid(user_sid)
            owner = security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
            if owner not in {user, security.ConvertSidToStringSid(default_owner_sid)}:
                return False
            return self._private_dacl(descriptor.GetSecurityDescriptorDacl(), user)
        except (OSError, pywintypes.error, ValueError, TypeError):
            return False

    def private_child(self, path: Path, *, fd: int) -> bool:
        # Windows traverse-bypass privilege means a private parent alone is
        # insufficient: the opened transcript must also have a private DACL.
        try:
            info, named = os.fstat(fd), path.lstat()
            return (info.st_nlink == 1 and stat.S_ISREG(info.st_mode)
                    and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino)
                    and self.private(path.parent) and self.private(path, fd=fd))
        except OSError:
            return False

    def ensure_directory(self, path: Path, *, repair: bool = False) -> None:
        if not self._real_chain(path):
            raise ValueError('private state cannot traverse a reparse point')
        if not path.exists():
            # Never use mkdir(parents=True) here: it creates missing ancestors
            # with inherited, potentially shared ACLs. Build each component
            # with the same user/SYSTEM descriptor, starting at the nearest
            # existing parent.
            if not path.parent.exists():
                self.ensure_directory(path.parent)
            attributes = pywintypes.SECURITY_ATTRIBUTES()
            attributes.SECURITY_DESCRIPTOR = self._descriptor(True)
            try:
                win32file.CreateDirectory(str(path), attributes)
            except pywintypes.error as exc:
                if exc.winerror != 183:  # ERROR_ALREADY_EXISTS
                    raise OSError(exc.winerror, str(exc)) from exc
        if repair and path.is_dir() and not self.private(path):
            descriptor = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
                security.OWNER_SECURITY_INFORMATION)
            if descriptor.GetSecurityDescriptorOwner() == self._user():
                self.protect(path)
        if not path.is_dir() or not self.private(path):
            raise ValueError('private state directory is unsafe')
