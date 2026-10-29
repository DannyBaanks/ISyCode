"""Probe only the owned VHD device traverse right; restore exact ACL."""
import json
from pathlib import Path
import sys
import tempfile
import win32file
import win32security as security
from isycode.windows_sandbox_storage_cli import load_storage_config
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
from isycode.platform_windows_sandbox_process import WindowsSandboxProcess

request = json.loads(Path('docs/platform-parity/evidence/windows-vhd-operator-request-20261014.json').read_text(encoding='utf-8-sig'))
config = load_storage_config(Path((Path(request['setup_root'])/'config-path.txt').read_text()))
with tempfile.TemporaryDirectory(prefix='isycode-device-control-') as source:
    with BoundedStorageProvider(config).open() as lease:
        with WindowsSandboxResources.prepare(Path(source), Path(sys.base_prefix), (), storage_lease=lease) as r:
            dos_root = Path(win32file.GetFinalPathNameByHandle(lease._holder.root_handle, 0)[4:])
            executable = dos_root / (r.runtime_root/'python.exe').relative_to(lease.root)
            device = win32file.CreateFile(config.volume_guid.rstrip('\\'), 0x60000, 7, None, 3, 0, None)
            original = security.GetSecurityInfo(int(device), security.SE_KERNEL_OBJECT,
                security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
            try:
                acl = security.ACL()
                for index in range(original.GetAceCount()):
                    (_, flags), mask, principal = original.GetAce(index)
                    acl.AddAccessAllowedAceEx(security.ACL_REVISION, flags, mask, principal)
                acl.AddAccessAllowedAceEx(security.ACL_REVISION, 0, 0x20, security.SID(r.profile_sid))
                security.SetSecurityInfo(int(device), security.SE_KERNEL_OBJECT,
                    security.DACL_SECURITY_INFORMATION, None, None, acl, None)
                code = ('from pathlib import Path\nprint("loader-control")\n'
                        'Path("owned.txt").write_text("owned-write")\n'
                        'import ctypes as c\nk=c.WinDLL("kernel32",use_last_error=True)\n'
                        'k.CreateFileW.argtypes=[c.c_wchar_p,c.c_ulong,c.c_ulong,c.c_void_p,c.c_ulong,c.c_ulong,c.c_void_p]\n'
                        'k.CreateFileW.restype=c.c_void_p\nk.CloseHandle.argtypes=[c.c_void_p]\n'
                        f'for access in (0x80000000,0x40000000):\n h=k.CreateFileW({config.volume_guid.rstrip(chr(92))!r},access,3,None,3,0,None)\n'
                        ' if h==c.c_void_p(-1).value: print("raw-denied",access,c.get_last_error())\n'
                        ' else: k.CloseHandle(h); raise RuntimeError("raw device access")\n')
                with WindowsSandboxProcess.launch(executable,(str(executable),'-I','-c',code),
                        dos_root/r.stage_root.relative_to(lease.root),r.environment,r.profile_sid,
                        256,r.capability_sids) as process:
                    print('exit',process.wait(20),'output',repr(process.read(8192)),flush=True)
                print('owned write:', (r.stage_root/'owned.txt').read_text(), flush=True)
                lease.assert_unchanged()
            finally:
                security.SetSecurityInfo(int(device),security.SE_KERNEL_OBJECT,
                    security.DACL_SECURITY_INFORMATION,None,None,original,None)
                device.Close()
                lease.assert_unchanged()
