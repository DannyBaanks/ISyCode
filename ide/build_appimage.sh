#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/danny/Development/IsyVM"
APPDIR="${REPO_DIR}/build/AppDir"
DIST_DIR="${REPO_DIR}/dist"
APPIMAGE_TOOL="/tmp/squashfs-root/AppRun"

echo "=== 1. Preparing AppDir structure ==="
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/scalable/apps"

echo "=== 2. Copying PyInstaller application ==="
cp -r "${DIST_DIR}/isycode_app" "${APPDIR}/usr/bin/isycode_app"

echo "=== 3. Setting up Desktop entry and Icons ==="
cat << 'EOF' > "${APPDIR}/isycode.desktop"
[Desktop Entry]
Name=ISyCode
GenericName=AI Agent Studio
Comment=ISyCode AI Agent Desktop Studio
Exec=isycode %F
Icon=isycode
Terminal=false
Type=Application
Categories=Development;IDE;Utility;
StartupWMClass=ISyCode
Keywords=ai;agent;isycode;code;assistant;
EOF

cp "${APPDIR}/isycode.desktop" "${APPDIR}/usr/share/applications/isycode.desktop"

# Icons
cp "${REPO_DIR}/ui/assets/isycode.png" "${APPDIR}/isycode.png"
cp "${REPO_DIR}/ui/assets/isycode.png" "${APPDIR}/.DirIcon"
cp "${REPO_DIR}/ui/assets/isycode.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/isycode.png"
cp "${REPO_DIR}/ui/assets/isycode.svg" "${APPDIR}/usr/share/icons/hicolor/scalable/apps/isycode.svg"

echo "=== 4. Setting up AppRun launcher ==="
cat << 'EOF' > "${APPDIR}/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${HERE}/usr/bin/isycode_app:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${HERE}/usr/bin/isycode_app:${LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="${HERE}/usr/bin/isycode_app/PySide6/plugins:${QT_PLUGIN_PATH}"
exec "${HERE}/usr/bin/isycode_app/isycode_app" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

echo "=== 5. Packaging AppImage with appimagetool ==="
export ARCH=x86_64
"${APPIMAGE_TOOL}" "${APPDIR}" "${REPO_DIR}/dist/ISyCode-x86_64.AppImage"

echo "=== AppImage build completed: ${REPO_DIR}/dist/ISyCode-x86_64.AppImage ==="
