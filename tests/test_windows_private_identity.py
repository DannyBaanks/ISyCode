"""Another native security principal cannot read private seeded application state."""
import os
import pytest
pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows anonymous token witness')


def test_anonymous_identity_cannot_read_private_metadata(tmp_path):
    import ctypes as c
    from ctypes import wintypes as w
    import win32api,win32file,pywintypes
    from isycode.platform_storage import storage
    root=tmp_path/'private-state';storage.ensure_directory(root)
    paths=[]
    for name in ('authority.json','action-audit.jsonl','credentials.sqlite3'):
        path=root/name;path.write_bytes(b'seeded-not-real-secret');storage.protect(path);paths.append(path)
    before=win32api.GetUserName()
    impersonate=c.WinDLL('advapi32',use_last_error=True).ImpersonateAnonymousToken
    impersonate.argtypes=[w.HANDLE];impersonate.restype=w.BOOL
    revert=c.WinDLL('advapi32',use_last_error=True).RevertToSelf
    revert.argtypes=[];revert.restype=w.BOOL
    assert impersonate(int(win32api.GetCurrentThread()))
    try:
        for path in paths:
            try:handle=win32file.CreateFile(str(path),0x80000000,7,None,3,0,None)
            except pywintypes.error as exc:assert exc.winerror==5
            else:handle.Close();pytest.fail('anonymous identity read private metadata')
    finally:
        assert revert()
    assert win32api.GetUserName()==before
    assert all(path.read_bytes()==b'seeded-not-real-secret' for path in paths)
