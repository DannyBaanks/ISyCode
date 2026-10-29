import ctypes as c,json
from ctypes import wintypes as w
from pathlib import Path
import win32file,win32security as s
from isycode.windows_sandbox_storage_cli import load_storage_config
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
req=json.loads(Path('docs/platform-parity/evidence/windows-vhd-operator-request-20261014.json').read_text(encoding='utf-8-sig'))
config=load_storage_config(Path((Path(req['setup_root'])/'config-path.txt').read_text()))
class IOSB(c.Structure):_fields_=[('status',c.c_void_p),('information',c.c_size_t)]
class Device(c.Structure):_fields_=[('type',w.ULONG),('characteristics',w.ULONG)]
query=c.WinDLL('ntdll').NtQueryVolumeInformationFile
query.argtypes=[w.HANDLE,c.POINTER(IOSB),c.c_void_p,w.ULONG,c.c_int];query.restype=w.LONG
with BoundedStorageProvider(config).open() as lease:
 device=Device();ios=IOSB()
 status=query(int(lease._holder.root_handle),c.byref(ios),c.byref(device),c.sizeof(device),4)
 assert status==0,status
 print('device characteristics:',hex(device.characteristics))
 assert not device.characteristics&0x100
 print('root descriptor:',s.ConvertSecurityDescriptorToStringSecurityDescriptor(s.GetNamedSecurityInfo(str(lease.root),s.SE_FILE_OBJECT,5),1,5))
 print('identity:',lease.identity.payload())
