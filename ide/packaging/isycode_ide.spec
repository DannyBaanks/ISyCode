# Independent desktop build; no historical AppDir or IsyVM path is used.
import os
import sys
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

bin_name = os.environ.get("ISYCODE_BIN_NAME", "isycode-ide")
icon_path = os.environ.get("ISYCODE_ICON_PATH") or None
onefile = os.environ.get("ISYCODE_ONEFILE", "").strip() in {"1", "true", "yes"}
console = sys.platform not in {"win32", "darwin"}

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=bin_name,
        console=console,
        icon=icon_path,
        strip=False,
        upx=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=bin_name,
        console=console,
        icon=icon_path,
        strip=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name=bin_name, strip=False, upx=False)
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="ISyCode IDE.app",
            icon=icon_path,
            bundle_identifier="com.isyco.isycode-ide",
        )
