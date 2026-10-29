"""Discover admin-installed Git without trusting cwd or the user's PATH."""
import os
import winreg
from pathlib import Path
import win32security as security
import pywintypes
from isycode.winfs import is_link


class WindowsGit:
    def __init__(self):
        # Reject write grants to unprivileged principals, including an owner
        # with implicit WRITE_DAC. Administrators/SYSTEM remain OS trust roots.
        trusted = {'S-1-5-18', 'S-1-5-32-544'}
        try:
            trusted.add(security.ConvertSidToStringSid(
                security.LookupAccountName(None, 'NT SERVICE\\TrustedInstaller')[0]))
        except pywintypes.error:
            pass
        self._trust_roots = frozenset(trusted)

    def _trusted(self, path):
        return self._safe_security(path, 0x0002 | 0x0004 | 0x0010 | 0x0040 | 0x0100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000)

    def _safe_security(self, item, dangerous):
        try:
            if is_link(item):
                return False
            descriptor = security.GetNamedSecurityInfo(str(item), security.SE_FILE_OBJECT,
                security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
            if security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) not in self._trust_roots:
                return False
            acl = descriptor.GetSecurityDescriptorDacl()
            if acl is None:
                return False
            for index in range(acl.GetAceCount()):
                (kind, flags), mask, sid = acl.GetAce(index)
                if kind == security.ACCESS_ALLOWED_ACE_TYPE and not flags & security.INHERIT_ONLY_ACE:
                    if mask & dangerous and security.ConvertSidToStringSid(sid) not in self._trust_roots:
                        return False
                elif kind not in {security.ACCESS_ALLOWED_ACE_TYPE, security.ACCESS_DENIED_ACE_TYPE}:
                    return False
            return True
        except (OSError, pywintypes.error, ValueError):
            return False

    def discover(self, directories=()):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\GitForWindows',
                                    0, winreg.KEY_READ | view) as key:
                    base, kind = winreg.QueryValueEx(key, 'InstallPath')
                if kind != winreg.REG_SZ or not isinstance(base, str) or not Path(base).is_absolute():
                    continue
                base = Path(base)
                if not self._trusted(base) or not all(self._safe_security(parent,
                        0x40 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000) for parent in base.parents):
                    continue
                # Invoke the native binary directly, not cmd/git.exe's shim.
                for architecture in ('mingw64', 'mingw32'):
                    native = base / architecture / 'bin'
                    path = native / 'git.exe'
                    if not path.is_file() or not self._trusted(path):
                        continue
                    locations = (native, base / architecture / 'libexec' / 'git-core', base / 'usr' / 'bin')
                    safe = True
                    for directory in locations:
                        components = (directory, *(parent for parent in directory.parents
                                      if parent == base or base in parent.parents))
                        if not directory.is_dir() or not all(self._trusted(component) for component in components):
                            safe = False
                            break
                        for dependency in directory.rglob('*'):
                            if is_link(dependency) or not self._trusted(dependency):
                                safe = False
                                break
                        if not safe:
                            break
                    if safe:
                        return str(path)
            except OSError:
                continue
        return None

    def environment(self, directories):
        executable = self.discover()
        environment = {'PATH': str(Path(executable).parent) if executable else ''}
        # Windows process startup and Git's user identity need OS/user locations.
        # Their values are inherited explicitly; executable discovery ignores PATH.
        for key in ('SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH'):
            if os.environ.get(key):
                environment[key] = os.environ[key]
        return environment
