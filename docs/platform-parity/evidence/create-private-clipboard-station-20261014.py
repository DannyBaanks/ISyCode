"""Temporary operator-owned test station; never accesses WinSta0 clipboard."""
import ctypes as c,time,sys
from ctypes import wintypes as w
from pathlib import Path
name,user,folder=sys.argv[1:]
assert name.startswith('isycode-clipboard-test-') and len(name)==len('isycode-clipboard-test-')+32
assert c.windll.shell32.IsUserAnAdmin()
root=Path(folder)
u=c.WinDLL('user32',use_last_error=True);a=c.WinDLL('advapi32',use_last_error=True);k=c.WinDLL('kernel32',use_last_error=True)
class SA(c.Structure):_fields_=[('size',w.DWORD),('descriptor',c.c_void_p),('inherit',w.BOOL)]
convert=a.ConvertStringSecurityDescriptorToSecurityDescriptorW
convert.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)];convert.restype=w.BOOL
pointer=c.c_void_p()
if not convert(f'O:{user}D:P(A;;GA;;;{user})(A;;GA;;;SY)',1,c.byref(pointer),None):raise c.WinError(c.get_last_error())
create=u.CreateWindowStationW;create.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.POINTER(SA)];create.restype=w.HANDLE
close=u.CloseWindowStation;close.argtypes=[w.HANDLE];close.restype=w.BOOL
free=k.LocalFree;free.argtypes=[c.c_void_p];free.restype=c.c_void_p
try:station=create(name,1,0x37f,c.byref(SA(c.sizeof(SA),pointer,False)))
finally:free(pointer)
if not station:raise c.WinError(c.get_last_error())
try:
 (root/'station-ready.txt').write_text(name,encoding='utf-8')
 deadline=time.monotonic()+150
 while not (root/'station-stop.txt').exists() and time.monotonic()<deadline:time.sleep(.1)
finally:close(station)
print('Closed temporary private test window station')
