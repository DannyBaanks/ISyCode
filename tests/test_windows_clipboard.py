"""Clipboard API controls; real roundtrip uses a separate window station."""
import os,subprocess,sys
from pathlib import Path
import pytest
pytestmark=pytest.mark.skipif(os.name!='nt',reason='native Windows clipboard')


def test_windows_clipboard_payload_preserves_unicode():
    from isycode.platform_windows_clipboard import encode_text
    text='Unicode ñ 東京 😀'
    assert encode_text(text).decode('utf-16-le')==text


def test_windows_clipboard_does_not_discover_writer_from_path(monkeypatch):
    from isycode import platform_windows_clipboard as clip
    monkeypatch.setenv('PATH','Z:\\untrusted')
    command=clip.system_clipboard_command()
    assert command and Path(command[0]).name.lower()=='clip.exe'
    assert Path(command[0]).is_absolute() and Path(command[0]).parent==Path(clip.win32api.GetSystemDirectory())


def test_windows_clipboard_real_isolated_roundtrip(tmp_path):
    script=r'''
import ctypes as c,sys,uuid,os
from ctypes import wintypes as w
u=c.WinDLL('user32',use_last_error=True)
u.CreateWindowStationW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p];u.CreateWindowStationW.restype=w.HANDLE
u.SetProcessWindowStation.argtypes=[w.HANDLE];u.SetProcessWindowStation.restype=w.BOOL
u.CreateDesktopW.argtypes=[w.LPCWSTR,w.LPCWSTR,c.c_void_p,w.DWORD,w.DWORD,c.c_void_p];u.CreateDesktopW.restype=w.HANDLE
u.SetThreadDesktop.argtypes=[w.HANDLE];u.SetThreadDesktop.restype=w.BOOL
name=os.environ.get('ISYCODE_TEST_CLIPBOARD_STATION')
if not name:raise SystemExit(77)
assert name.startswith('isycode-clipboard-test-')
u.OpenWindowStationW.argtypes=[w.LPCWSTR,w.BOOL,w.DWORD];u.OpenWindowStationW.restype=w.HANDLE
station=u.OpenWindowStationW(name,False,0x37f)
if not station:raise c.WinError(c.get_last_error())
if not u.SetProcessWindowStation(station):raise c.WinError(c.get_last_error())
desktop=u.CreateDesktopW('default',None,None,0,0x1ff,None)
if not desktop or not u.SetThreadDesktop(desktop):raise c.WinError(c.get_last_error())
# CWF_CREATE_ONLY refuses existing stations; NULL uses a separate logon station.
from isycode.platform_windows_clipboard import _desktop_name
assert not _desktop_name().casefold().startswith('winsta0\\')
# Never open the user's WinSta0 clipboard.
from pathlib import Path
from isycode.clipboard_owner import ClipboardOwner
from isycode.workspace_authority import WorkspaceAuthority
root=Path(sys.argv[1]);root.mkdir()
authority=WorkspaceAuthority(root)
owner=ClipboardOwner(root,authority)
assert owner.paste()[0].decision=='DENY'
authority.set_grant('clipboard.copy',enabled=True,targets=['clipboard'])
authority.set_grant('clipboard.paste',enabled=True,targets=['clipboard'])
for text in ('Unicode ñ 東京 😀','東京','😀','A','\ufeffcontent'):
 text='Unicode ñ 東京 😀'
 result=owner.copy(text,source='selection')
 assert result.decision=='ALLOW',result
 outcome,mime,data=owner.paste()
 assert outcome.decision=='ALLOW',(outcome,mime)
 assert mime=='text/plain' and data.decode('utf-8')==text,(mime,data)
print('isolated station: Unicode copy/paste, grants, receipts PASS')
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path/'workspace')],capture_output=True,text=True,timeout=30)
    if result.returncode==77:pytest.skip('NOT_DEMONSTRATED: isolated operator-created clipboard station required')
    assert result.returncode==0,result.stderr
    assert 'receipts PASS' in result.stdout


def test_windows_clipboard_refuses_oversize_before_memory_copy(monkeypatch):
    from isycode import platform_windows_clipboard as clip
    closed=[]
    monkeypatch.setattr(clip,'_open',lambda window:True)
    monkeypatch.setattr(clip,'_close',lambda:closed.append(True))
    monkeypatch.setattr(clip,'_register',lambda name:99)
    monkeypatch.setattr(clip,'_available',lambda format_id:format_id==13)
    monkeypatch.setattr(clip,'_get',lambda format_id:42)
    monkeypatch.setattr(clip,'_size',lambda handle:2*clip.MAX_BYTES+4)
    monkeypatch.setattr(clip,'_lock',lambda handle:pytest.fail('oversize memory was accessed'))
    with pytest.raises(ValueError,match='limit'):clip._read_windows_clipboard()
    assert closed==[True]


def test_windows_clipboard_text_drops_utf16_bom(monkeypatch):
    import ctypes as c
    from isycode import platform_windows_clipboard as clip
    raw=(chr(0xfeff)+'Unicode ñ 東京 😀\0').encode('utf-16-le')
    payload=c.create_string_buffer(raw)
    monkeypatch.setattr(clip,'_open',lambda window:True)
    monkeypatch.setattr(clip,'_close',lambda:None)
    monkeypatch.setattr(clip,'_register',lambda name:0)
    monkeypatch.setattr(clip,'_available',lambda format_id:format_id==13)
    monkeypatch.setattr(clip,'_get',lambda format_id:42)
    monkeypatch.setattr(clip,'_size',lambda handle:len(raw))
    monkeypatch.setattr(clip,'_lock',lambda handle:c.addressof(payload))
    monkeypatch.setattr(clip,'_unlock',lambda handle:True)

    mime,data=clip._read_windows_clipboard()

    assert mime=='text/plain'
    assert data=='Unicode ñ 東京 😀'.encode('utf-8')


def test_windows_clipboard_worker_has_timeout_and_private_desktop(monkeypatch):
    from isycode import platform_windows_clipboard as clip
    monkeypatch.setattr(clip,'_desktop_name',lambda:'private-station\\private-desktop')
    def timeout(argv,**kwargs):
        assert kwargs['timeout']==3 and kwargs['close_fds']
        assert kwargs['startupinfo'].lpDesktop=='private-station\\private-desktop'
        assert kwargs['creationflags']==subprocess.CREATE_NO_WINDOW
        raise subprocess.TimeoutExpired(argv,3)
    monkeypatch.setattr(clip.subprocess,'run',timeout)
    with pytest.raises(subprocess.TimeoutExpired):clip.read_system_clipboard()
