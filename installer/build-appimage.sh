#!/usr/bin/env bash
# PawPoller Linux AppImage builder
# ================================
#
# Run from the PawPoller repo root after `pyinstaller pawpoller.spec`
# has produced dist/PawPoller/. Emits installer/Output/PawPoller-{ver}-x86_64.AppImage.
#
# Driven by CI from .github/workflows/build.yml. Local runs need
# appimagetool on PATH (auto-downloads if not).
#
# Usage:  ./installer/build-appimage.sh <version>
#   e.g.  ./installer/build-appimage.sh 2.25.0

set -euo pipefail

VERSION="${1:-0.0.0-dev}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist/PawPoller"
OUTPUT_DIR="${REPO_ROOT}/installer/Output"
APPDIR="${REPO_ROOT}/installer/PawPoller.AppDir"

if [[ ! -d "${DIST_DIR}" ]]; then
  echo "ERROR: ${DIST_DIR} not found — run PyInstaller first" >&2
  exit 1
fi

echo "==> Building PawPoller AppImage v${VERSION}"

# Fresh AppDir every run so reruns don't accumulate cruft.
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${OUTPUT_DIR}"

# Copy the whole PyInstaller --onedir tree. PawPoller is the binary;
# _internal/ has its bundled libs (Qt, WebEngine, WeasyPrint, etc.).
cp -r "${DIST_DIR}" "${APPDIR}/usr/bin/PawPoller"

# AppRun is what the AppImage runtime exec's when the user runs the
# .AppImage. Resolves its own location, exec's the bundled binary.
cat > "${APPDIR}/AppRun" <<'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/PawPoller/PawPoller" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

# Desktop entry — required by AppImage spec. The DBus/notification
# system uses Icon= for the toast icon if notify-send is invoked
# without explicit --icon.
cat > "${APPDIR}/PawPoller.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=PawPoller
GenericName=Multi-platform story publisher
Comment=Multi-platform story publishing + analytics for furry fiction
Exec=PawPoller
Icon=PawPoller
Categories=Office;Publishing;
Terminal=false
StartupNotify=true
DESKTOP

# Icon — AppImage requires a top-level PNG matching the desktop entry's
# Icon= field. assets/tray_icon.png is sized for the system tray (small)
# but appimagetool accepts any size; bigger is better for the launcher's
# icon-picker rendering. Copy + symlink for .DirIcon (AppImage runtime
# reads .DirIcon for the file-manager preview).
cp "${REPO_ROOT}/assets/tray_icon.png" "${APPDIR}/PawPoller.png"
ln -sf PawPoller.png "${APPDIR}/.DirIcon"

# Acquire appimagetool if not on PATH. CI sets it up in the workflow;
# this branch covers local runs.
if ! command -v appimagetool >/dev/null 2>&1; then
  echo "==> appimagetool not on PATH, downloading continuous build…"
  curl -fsSL -o /tmp/appimagetool \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x /tmp/appimagetool
  APPIMAGETOOL=/tmp/appimagetool
else
  APPIMAGETOOL=appimagetool
fi

OUTPUT_FILE="${OUTPUT_DIR}/PawPoller-${VERSION}-x86_64.AppImage"

# ARCH=x86_64 hints appimagetool when running on a build machine that
# could be ambiguous (e.g. CI containers). VERSION goes into the
# embedded metadata for `appimagetool --get-bundle-id` etc.
ARCH=x86_64 VERSION="${VERSION}" "${APPIMAGETOOL}" \
  --no-appstream \
  "${APPDIR}" \
  "${OUTPUT_FILE}"

echo "==> Built ${OUTPUT_FILE}"
ls -lh "${OUTPUT_FILE}"
