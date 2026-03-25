#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PKG_NAME="Claude_Usage"
VERSION="1.2.0"
ARCH="x86_64"

# Require appimagetool
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
if ! command -v "$APPIMAGETOOL" &>/dev/null; then
    if [ -x /tmp/appimagetool ]; then
        APPIMAGETOOL=/tmp/appimagetool
    else
        echo "ERROR: appimagetool not found. Install it or set APPIMAGETOOL env var."
        echo "  curl -fsSL -o /tmp/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
        echo "  chmod +x /tmp/appimagetool"
        exit 1
    fi
fi

echo "==> Building ${PKG_NAME}-${VERSION}-${ARCH}.AppImage"

# Create AppDir
APPDIR="$(mktemp -d)/AppDir"
trap 'rm -rf "$(dirname "$APPDIR")"' EXIT
mkdir -p "$APPDIR"

# --- Python package ---
SITE_PKG="$APPDIR/usr/lib/python3/dist-packages/claude_usage"
mkdir -p "$SITE_PKG"
cp "$PROJECT_DIR/claude_usage/"*.py "$SITE_PKG/"

# Copy resources
if [ -d "$PROJECT_DIR/claude_usage/resources" ] && [ "$(ls -A "$PROJECT_DIR/claude_usage/resources" 2>/dev/null)" ]; then
    mkdir -p "$SITE_PKG/resources"
    cp -r "$PROJECT_DIR/claude_usage/resources/"* "$SITE_PKG/resources/"
fi

# --- AppRun ---
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
set -e

HERE="$(dirname "$(readlink -f "$0")")"

# Check dependencies
missing=""
python3 -c "import gi" 2>/dev/null || missing="$missing python3-gi"
python3 -c "import gi; gi.require_version('Gtk', '4.0')" 2>/dev/null || missing="$missing gir1.2-gtk-4.0"

if [ -n "$missing" ]; then
    echo "Missing system dependencies:$missing"
    echo ""
    echo "Install them with:"
    echo "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7"
    exit 1
fi

export PYTHONPATH="$HERE/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
exec python3 -m claude_usage "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# --- Desktop entry ---
cat > "$APPDIR/claude-usage.desktop" << DESKTOP
[Desktop Entry]
Name=Claude Usage
Comment=Monitor your Claude API usage
Exec=claude-usage
Icon=claude-usage
Type=Application
Categories=Utility;Monitor;
StartupNotify=false
DESKTOP

# --- Icon ---
if [ -f "$PROJECT_DIR/claude_usage/resources/claude-usage.png" ]; then
    cp "$PROJECT_DIR/claude_usage/resources/claude-usage.png" "$APPDIR/claude-usage.png"
    # Also install in standard icon dirs for desktop integration
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    cp "$PROJECT_DIR/claude_usage/resources/claude-usage.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/claude-usage.png"
else
    echo "WARNING: Icon not found, creating placeholder"
    # Create a minimal 1x1 PNG placeholder
    printf '\x89PNG\r\n\x1a\n' > "$APPDIR/claude-usage.png"
fi

# --- Permissions ---
find "$APPDIR/usr" -type f -exec chmod 644 {} +
find "$APPDIR/usr" -type d -exec chmod 755 {} +
chmod +x "$APPDIR/AppRun"

# --- Build AppImage ---
OUTPUT_DIR="$PROJECT_DIR"
ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUTPUT_DIR/${PKG_NAME}-${VERSION}-${ARCH}.AppImage"

echo "==> AppImage built: $OUTPUT_DIR/${PKG_NAME}-${VERSION}-${ARCH}.AppImage"
