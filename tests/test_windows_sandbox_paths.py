"""Handle-bound launch aliases; SDK fakes do not certify VHD isolation."""
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='native image handles')
GUID='\\\\?\\Volume{11111111-2222-3333-4444-555555555555}\\runtime\\python.exe'


def sdk(monkeypatch, *, guid=GUID, dos=r'\\?\Q:\runtime\python.exe'):
    from isycode import platform_windows_sandbox_process as native
    handle=SimpleNamespace(closed=False)
    def close(): handle.closed=True
    handle.Close=close
    monkeypatch.setattr(native.win32file,'CreateFile',lambda *args:handle)
    monkeypatch.setattr(native.win32file,'GetFinalPathNameByHandle',lambda h,flags:
        {0:dos,1:guid,2:r'\Device\HarddiskVolume42\runtime\python.exe'}[flags])
    monkeypatch.setattr(native.win32file,'GetFileInformationByHandle',lambda h:(0,0,0,0,0,0,0,1,0,1))
    return native,handle


def test_guid_launch_uses_measured_alias_and_pins_image(monkeypatch):
    native,handle=sdk(monkeypatch)
    image=native.LaunchImage.open(Path(GUID))
    try:
        assert image.path==r'Q:\runtime\python.exe'
        assert image.native_path==r'\Device\HarddiskVolume42\runtime\python.exe'
        assert not handle.closed
    finally:image.close()
    assert handle.closed


@pytest.mark.parametrize('changed',[
    {'guid':GUID.replace('11111111','99999999')},
    {'dos':r'\\?\Volume{11111111-2222-3333-4444-555555555555}\runtime\python.exe'},
    {'dos':r'\\?\UNC\server\share\python.exe'}])
def test_unmatched_or_missing_alias_fails_closed(monkeypatch,changed):
    native,handle=sdk(monkeypatch,**changed)
    with pytest.raises(OSError): native.LaunchImage.open(Path(GUID))
    assert handle.closed


def test_native_mapping_is_checked_again_before_resume(monkeypatch):
    native,handle=sdk(monkeypatch)
    image=native.LaunchImage.open(Path(GUID))
    try:
        monkeypatch.setattr(native,'mapped_image',lambda _:image.native_path)
        image.verify(123)
        monkeypatch.setattr(native,'mapped_image',lambda _:r'\Device\HarddiskVolume99\runtime\python.exe')
        with pytest.raises(OSError,match='mapping'):image.verify(123)
    finally:image.close()


def test_verified_fs_keeps_lexical_root_when_windows_has_a_volume_alias(tmp_path, monkeypatch):
    from isycode import winfs
    canonical=tmp_path/'canonical-alias'
    original=winfs.os.path.realpath
    monkeypatch.setattr(winfs.os.path,'realpath',lambda path,**kw:
        str(canonical) if Path(path)==tmp_path else original(path,**kw))
    fs=winfs.VerifiedFS(tmp_path)
    fs.check_chain(tmp_path/'result.txt')
    assert fs._inside(str(canonical/'result.txt'))
    assert not fs._inside(str(tmp_path.parent/'outside.txt'))


def test_verified_fs_rejects_root_alias_retarget(tmp_path, monkeypatch):
    from isycode import winfs
    fs=winfs.VerifiedFS(tmp_path)
    monkeypatch.setattr(winfs.os.path,'realpath',lambda path,**kw:str(tmp_path.parent/'outside'))
    with pytest.raises(OSError,match='root'):
        fs.check_chain(tmp_path/'result.txt')


def test_verified_fs_extended_dos_alias_has_same_containment_key():
    from isycode.winfs import VerifiedFS
    assert VerifiedFS._path_key(r'\\?\Q:\workspace')==VerifiedFS._path_key(r'Q:\workspace')
    assert VerifiedFS._path_key(r'\\?\UNC\host\share')==VerifiedFS._path_key(r'\\host\share')
