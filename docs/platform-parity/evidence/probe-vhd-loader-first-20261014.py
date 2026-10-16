"""Controlled loader diagnosis; restore the owned VHD root ACL in finally."""
import json
from pathlib import Path
import sys
import tempfile

import win32con
import win32file
import win32security as security

from isycode.windows_sandbox_storage_cli import load_storage_config
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
from isycode import platform_windows_sandbox_process as native

root = Path.cwd()
request = json.loads((root/'docs/platform-parity/evidence/windows-vhd-operator-request-20261014.json').read_text(encoding='utf-8-sig'))
config = load_storage_config(Path((Path(request['setup_root'])/'config-path.txt').read_text()))
with tempfile.TemporaryDirectory(prefix='isycode-loader-control-') as source:
    with BoundedStorageProvider(config).open() as lease:
        with WindowsSandboxResources.prepare(Path(source), Path(sys.base_prefix), (), storage_lease=lease) as resource:
            dos_root = Path(win32file.GetFinalPathNameByHandle(lease._holder.root_handle, 0)[4:])
            def dos(path): return dos_root / Path(path).relative_to(lease.root)
            executable = dos(resource.runtime_root / 'python.exe')
            cwd = dos(resource.stage_root)
            original_guard = native.restrict_profile_registry
            original_acl = security.GetSecurityInfo(int(lease._holder.root_handle), security.SE_FILE_OBJECT,
                security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
            sid = security.SID(resource.profile_sid)
            results = []
            def guard(process, profile_sid):
                original_guard(process, profile_sid)
                token = security.OpenProcessToken(process, win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE)
                control = []
                try:
                    security.ImpersonateLoggedOnUser(token)
                    try:
                        for path in (dos_root, resource.runtime_root/'python312.dll',
                                     dos(resource.runtime_root/'python312.dll')):
                            try:
                                handle = win32file.CreateFile(str(path), 0x80000000, 7, None, 3,
                                                             0x02000000, None)
                            except Exception as exc:
                                control.append((str(path), getattr(exc, 'winerror', None)))
                            else:
                                handle.Close()
                                control.append((str(path), 'READ_ALLOWED'))
                    finally:
                        security.RevertToSelf()
                finally:
                    token.Close()
                results.append(control)
            native.restrict_profile_registry = guard
            try:
                for variant in ('original', 'dos-environment', 'traverse-only'):
                    environment = dict(resource.environment)
                    if variant != 'original':
                        for name in ('TEMP', 'TMP', 'LOCALAPPDATA', 'PATH'):
                            environment[name] = str(dos(environment[name]))
                    if variant == 'traverse-only':
                        acl = security.ACL()
                        for index in range(original_acl.GetAceCount()):
                            acl.AddAce(security.ACL_REVISION, acl.GetAceCount(), original_acl.GetAce(index))
                        acl.AddAccessAllowedAceEx(security.ACL_REVISION, 0, 0x20, sid)
                        security.SetSecurityInfo(int(lease._holder.root_handle), security.SE_FILE_OBJECT,
                            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                            None, None, acl, None)
                    try:
                        with native.WindowsSandboxProcess.launch(executable,
                                (str(executable), '-I', '-c', 'print("loader-control")'), cwd,
                                environment, resource.profile_sid, 256, resource.capability_sids) as process:
                            status, output = process.wait(15), process.read(4096)
                        print(variant, 'exit', status, 'output', repr(output), 'access', results[-1], flush=True)
                    except Exception as exc:
                        print(variant, 'error', type(exc).__name__, str(exc), flush=True)
            finally:
                native.restrict_profile_registry = original_guard
                security.SetNamedSecurityInfo(str(lease.root), security.SE_FILE_OBJECT,
                    security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                    None, None, original_acl, None)
                lease.assert_unchanged()
