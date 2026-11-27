#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/danny/Development/IsyVM"
APPIMAGE_SRC="${REPO_DIR}/dist/ISyCode-x86_64.AppImage"
APPS_DIR="${HOME}/Applications"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_256_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
ICON_SVG_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
PIXMAPS_DIR="${HOME}/.local/share/pixmaps"

if [ ! -f "${APPIMAGE_SRC}" ]; then
    echo "Error: AppImage not found at ${APPIMAGE_SRC}. Run build_appimage.sh first."
    exit 1
fi

echo "=== 1. Creating user directories ==="
mkdir -p "${APPS_DIR}"
mkdir -p "${BIN_DIR}"
mkdir -p "${DESKTOP_DIR}"
mkdir -p "${ICON_256_DIR}"
mkdir -p "${ICON_SVG_DIR}"
mkdir -p "${PIXMAPS_DIR}"

echo "=== 2. Installing AppImage binary ==="
cp "${APPIMAGE_SRC}" "${APPS_DIR}/ISyCode.AppImage.new"
chmod +x "${APPS_DIR}/ISyCode.AppImage.new"
mv -f "${APPS_DIR}/ISyCode.AppImage.new" "${APPS_DIR}/ISyCode.AppImage"

# Create/update symlink in ~/.local/bin/isycode-app
ln -sf "${APPS_DIR}/ISyCode.AppImage" "${BIN_DIR}/isycode-app"

echo "=== 3. Installing Icons ==="
for res in 48x48 64x64 128x128 256x256 512x512; do
    mkdir -p "${HOME}/.local/share/icons/hicolor/${res}/apps"
    if [ -f "${REPO_DIR}/ui/assets/isycode_${res}.png" ]; then
        cp "${REPO_DIR}/ui/assets/isycode_${res}.png" "${HOME}/.local/share/icons/hicolor/${res}/apps/isycode.png"
    fi
done
cp "${REPO_DIR}/ui/assets/isycode.svg" "${ICON_SVG_DIR}/isycode.svg"
cp "${REPO_DIR}/ui/assets/isycode.png" "${PIXMAPS_DIR}/isycode.png"

# Also install icon directly as absolute path fallback in desktop entry
ICON_PATH="${HOME}/.local/share/icons/hicolor/512x512/apps/isycode.png"

echo "=== 4. Installing Desktop Entry ==="
cat << EOF > "${DESKTOP_DIR}/isycode.desktop"
[Desktop Entry]
Name=ISyCode
GenericName=AI Agent Studio
Comment=ISyCode AI Agent Desktop Studio
Exec=${APPS_DIR}/ISyCode.AppImage %F
Icon=${ICON_PATH}
Terminal=false
Type=Application
Categories=Development;IDE;
StartupWMClass=ISyCode
Keywords=ai;agent;isycode;code;assistant;
EOF

chmod +x "${DESKTOP_DIR}/isycode.desktop"

echo "=== 5. Updating Desktop Database & Icon Cache ==="
if command -v update-desktop-database > /dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}"
fi
if command -v gtk-update-icon-cache > /dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" || true
fi

echo "=== ISyCode AppImage successfully installed! ==="
echo "Path: ${APPS_DIR}/ISyCode.AppImage"
echo "CLI (Desktop App): ${BIN_DIR}/isycode-app"
echo "CLI (Mainline TUI): ${BIN_DIR}/isycode"
echo "Desktop: ${DESKTOP_DIR}/isycode.desktop"
