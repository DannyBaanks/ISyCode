"""Operator-only exact owned-VHD disappearance control; no format/data deletion."""
import ctypes as c,json,os,sys,time
from ctypes import wintypes as w
from pathlib import Path
import win32api,win32con,win32security as security,pywintypes
from isycode import platform_windows_sandbox_volume_api as api
from isycode.platform_windows_sandbox_volume import validate_observation
from isycode.windows_sandbox_storage_cli import load_storage_config
config=load_storage_config(Path(sys.argv[1]));folder=Path(sys.argv[2])
assert c.windll.shell32.IsUserAnAdmin()
assert validate_observation(config,api.inspect_volume(config))==config.registered_identity
class Range(c.Structure):_fields_=[('offset',c.c_ulonglong),('length',c.c_ulonglong)]
class Data(c.Union):_fields_=[('reserved',w.DWORD),('range',Range)]
class Parameters(c.Structure):_fields_=[('version',w.DWORD),('data',Data)]
def wait(name):
 deadline=time.monotonic()+90
 while not (folder/name).exists():
  if time.monotonic()>deadline:raise TimeoutError(name)
  time.sleep(.05)
def write(name,payload):
 (folder/name).write_text(json.dumps(payload),encoding='utf-8')
virtual=c.WinDLL('virtdisk')
detach=virtual.DetachVirtualDisk;detach.argtypes=[w.HANDLE,w.DWORD,w.ULONG];detach.restype=w.DWORD
attach=virtual.AttachVirtualDisk;attach.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,w.ULONG,c.POINTER(Parameters),c.c_void_p];attach.restype=w.DWORD
token=security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY|win32con.TOKEN_ADJUST_PRIVILEGES)
previous=security.AdjustTokenPrivileges(token,False,[(security.LookupPrivilegeValue(None,'SeManageVolumePrivilege'),2)])
disk=None;fd=None;validated=False;detachment_attempted=False
try:
 fd=os.open(config.backing_file,os.O_RDONLY|os.O_BINARY)
 storage=api.VIRTUAL_STORAGE_TYPE(2,api.GUID.from_buffer_copy(api._MICROSOFT.bytes_le))
 handle=w.HANDLE();parameters=api.OPEN_PARAMETERS(1,1)
 api._check(api._open_disk(c.byref(storage),str(config.backing_file),0xe0000,0,c.byref(parameters),c.byref(handle)),'control image open')
 disk=pywintypes.HANDLE(handle.value)
 image=api._image_info(fd,disk)
 assert image.image_identifier==config.registered_identity.image_identifier
 assert image.backing_file_id==config.registered_identity.backing_file_id
 assert image.fixed and image.device_id==2 and image.virtual_bytes==512*1024**2
 validated=True
 write('operator-ready.json',{'image':image.image_identifier})
 wait('lease-ready.json')
 detachment_attempted=True
 code=detach(int(disk),0,0)
 still_attached=api._query_disk(disk,13).loaded!=0
 write('lease-attempt.json',{'detach_code':code,'still_attached':still_attached})
 wait('lease-released.json')
 if still_attached:api._check(detach(int(disk),0,0),'idle owned image detach')
 assert not api._query_disk(disk,13).loaded
 write('absent-ready.json',{'image':image.image_identifier,'attached':False})
 wait('missing-checked.json')
except BaseException as exc:
 write('operator-error.json',{'error':str(exc)})
 raise
finally:
 try:
  if disk is not None and validated and detachment_attempted:
   if not api._query_disk(disk,13).loaded:
    parameters=Parameters(1)
    api._check(attach(int(disk),None,0x14,0,c.byref(parameters),None),'restore exact owned VHD')
   write('reattached.json',{'image':api._guid(api._query_disk(disk,2).identifier),'attached':True})
 finally:
  try:
   if disk is not None:disk.Close()
   if fd is not None:os.close(fd)
  finally:
   try:security.AdjustTokenPrivileges(token,False,previous)
   finally:token.Close()
print('Exact image restored after real disappearance control')
