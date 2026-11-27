"""Install a new IDE launcher and desktop entry without replacing existing files."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("appimage")
    parser.add_argument("--name", default="isycode-ide", help="New command and desktop ID")
    args = parser.parse_args()
    if not re.fullmatch(r"isycode-ide(?:-[a-z0-9-]+)?", args.name):
        parser.error("Use isycode-ide or an isycode-ide- suffix")
    image = Path(args.appimage).expanduser().resolve(strict=True)
    if not image.is_file() or not os.access(image, os.X_OK):
        parser.error("Choose an executable AppImage")
    home = Path.home()
    command = home / ".local/bin" / args.name
    desktop = home / ".local/share/applications" / (args.name + ".desktop")
    icon = home / ".local/share/icons/hicolor/256x256/apps" / (args.name + ".png")
    for target in (command, desktop, icon):
        if target.exists() or target.is_symlink():
            parser.error("Existing file preserved: " + str(target) + "; choose a new --name")
        target.parent.mkdir(parents=True, exist_ok=True)
    # Extraction mode also works on systems lacking a functioning FUSE mount.
    with command.open("x") as stream:
        stream.write("#!/bin/sh\nexport APPIMAGE_EXTRACT_AND_RUN=1\nexec " + shlex.quote(str(image)) + ' "$@"\n')
    command.chmod(0o755)
    with icon.open("xb") as output, (Path(__file__).parent.parent / "ui/assets/isycode_256x256.png").open("rb") as source:
        shutil.copyfileobj(source, output)
    with desktop.open("x") as stream:
        stream.write("[Desktop Entry]\nType=Application\nName=ISyCode IDE\nComment=Programación con agentes y cambios revisados\n"
                     "Exec=\"" + str(command).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + "\" %f\n"
                     "Icon=" + str(icon) + "\nTerminal=false\nCategories=Development;IDE;\nStartupWMClass=ISyCode IDE\n")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(desktop.parent)], capture_output=True)
    print(command)
    print(desktop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
