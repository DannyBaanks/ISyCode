"""Additive build: new output directory per invocation, no cleanup/overwrite."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--appimagetool", help="Explicit installed appimagetool executable")
    parser.add_argument("--runtime-file", help="Explicit pinned AppImage runtime ELF")
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    output = root / "dist" / ("ide-" + tag)
    work = root / "build" / ("ide-" + tag)
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "PyInstaller", "--distpath", str(output), "--workpath", str(work), str(root / "packaging/isycode_ide.spec")]
    with (output / "build.log").open("w") as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print("Build failed; preserved log: " + str(output / "build.log"))
        return result.returncode
    appdir = output / "ISyCode-IDE.AppDir"
    appdir.mkdir()
    shutil.copytree(output / "isycode-ide", appdir / "usr/lib/isycode-ide")
    desktop = (root / "packaging/isycode-ide.desktop").read_text().replace("Exec=isycode-ide %f", "Exec=AppRun %f")
    (appdir / "isycode-ide.desktop").write_text(desktop)
    shutil.copy2(root / "ui/assets/isycode.png", appdir / "isycode-ide.png")
    (appdir / ".DirIcon").symlink_to("isycode-ide.png")
    launcher = appdir / "AppRun"
    launcher.write_text('#!/bin/sh\napp_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$app_dir/usr/lib/isycode-ide/isycode-ide" "$@"\n')
    launcher.chmod(0o755)
    artifacts = [appdir / "usr/lib/isycode-ide/isycode-ide"]
    if options.appimagetool:
        tool = Path(options.appimagetool).resolve(strict=True)
        image = output / "ISyCode-IDE-x86_64.AppImage"
        env = dict(os.environ, ARCH="x86_64")
        command = [str(tool), "--no-appstream"]
        if options.runtime_file:
            command += ["--runtime-file", str(Path(options.runtime_file).resolve(strict=True))]
        command += [str(appdir), str(image)]
        result = subprocess.run(command, env=env)
        if result.returncode:
            return result.returncode
        artifacts.append(image)
    manifest = {"command": command, "output": str(output), "artifacts": [
        {"path": str(path), "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest()} for path in artifacts]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
