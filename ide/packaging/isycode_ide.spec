# Independent desktop build; no historical AppDir or IsyVM path is used.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
hidden = []
for package in ("core", "bridge", "ui", "isyvm", "isycode_ide", "markdown", "pygments", "textual"):
    hidden.extend(collect_submodules(package))
datas = [(str(root / "ui/assets"), "ui/assets"),
         (str(root / "core/runtime/linux.py"), "core/runtime"),
         (str(root / "core/runtime/linux_runner.py"), "core/runtime"),
         (str(root / "GUIA.md"), ".")]
a = Analysis([str(root / "packaging/ide_entry.py")], pathex=[str(root)],
             datas=datas, hiddenimports=hidden, excludes=["PyQt5", "PyQt6", "PySide2"], optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="isycode-ide",
          console=True, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="isycode-ide", strip=False, upx=False)
