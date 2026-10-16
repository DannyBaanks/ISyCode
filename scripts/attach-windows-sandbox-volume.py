"""Operator-only exact-image reattach using the standard disk security policy."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import win32api
import win32con
import win32security as security
from isycode import platform_windows_sandbox_volume_api as api


class Range(c.Structure):
    _fields_=[('offset',c.c_ulonglong),('length',c.c_ulonglong)]


class AttachData(c.Union):
    _fields_=[('reserved',w.DWORD),('range',Range)]


class AttachParameters(c.Structure):
    _fields_=[('version',w.DWORD),('data',AttachData)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--expected-image-id',required=True)
    parser.add_argument('--new-attachment',action='store_true')
    args=parser.parse_args()
    if not c.windll.shell32.IsUserAnAdmin():
        raise OSError('Administrative operator required')
    observed=api.inspect_image(args.image)
    if (not observed.fixed or observed.device_id!=2 or observed.virtual_bytes!=512*1024**2
            or observed.image_identifier!=args.expected_image_id):
        raise OSError('Selected image identity is not the dedicated fixed VHD')
    if args.new_attachment and observed.physical_device:
        raise OSError('New attachment requires an unattached image')
    token=security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY|win32con.TOKEN_ADJUST_PRIVILEGES)
    previous=security.AdjustTokenPrivileges(token,False,[(security.LookupPrivilegeValue(None,'SeManageVolumePrivilege'),2)])
    disk=None
    try:
        storage=api.VIRTUAL_STORAGE_TYPE(2,api.GUID.from_buffer_copy(api._MICROSOFT.bytes_le))
        handle=w.HANDLE()
        params=api.OPEN_PARAMETERS(1,1)
        api._check(api._open_disk(c.byref(storage),str(args.image),0xe0000,0,c.byref(params),c.byref(handle)),'operator image open')
        import pywintypes
        disk=pywintypes.HANDLE(handle.value)
        if api._guid(api._query_disk(disk,2).identifier)!=args.expected_image_id:
            raise OSError('Opened image identity changed')
        actual_storage=api._query_disk(disk,6).storage
        if (api._query_disk(disk,7).subtype!=2
                or api._query_disk(disk,1).size.virtual!=512*1024**2
                or actual_storage.DeviceId!=2
                or bytes(actual_storage.VendorId)!=api._MICROSOFT.bytes_le):
            raise OSError('Opened image geometry or provider changed')
        virtual=c.WinDLL('virtdisk')
        detach=virtual.DetachVirtualDisk
        detach.argtypes=[w.HANDLE,w.DWORD,w.ULONG];detach.restype=w.DWORD
        attach=virtual.AttachVirtualDisk
        attach.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,w.ULONG,c.POINTER(AttachParameters),c.c_void_p]
        attach.restype=w.DWORD
        if not args.new_attachment:
            api._check(detach(int(disk),0,0),'operator image detach')
        parameters=AttachParameters(1)
        # PERMANENT_LIFETIME | NO_SECURITY_DESCRIPTOR: no per-image device filter.
        api._check(attach(int(disk),None,0x14,0,c.byref(parameters),None),'operator standard-policy attach')
        print('Attached exact VHD with system-default device policy:',args.expected_image_id)
    finally:
        try:
            if disk is not None:disk.Close()
        finally:
            try:security.AdjustTokenPrivileges(token,False,previous)
            finally:token.Close()


if __name__=='__main__':main()
