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

# --- AppRun (auto-installs missing deps on first run) ---
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
set -e

HERE="$(dirname "$(readlink -f "$0")")"
DEPS="python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7"

# Check which dependencies are missing
missing=""
for pkg in $DEPS; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        missing="$missing $pkg"
    fi
done

# Auto-install missing deps with a graphical prompt
if [ -n "$missing" ]; then
    msg="Claude Usage needs to install system libraries (one-time setup):\n\n$missing\n\nInstall now?"

    # Try graphical dialogs, fall back to terminal
    confirmed=false
    if command -v zenity &>/dev/null; then
        zenity --question --title="Claude Usage — First Run" \
            --text="$msg" --width=400 2>/dev/null && confirmed=true
    elif command -v kdialog &>/dev/null; then
        kdialog --yesno "$msg" --title "Claude Usage — First Run" 2>/dev/null && confirmed=true
    else
        echo -e "$msg"
        read -rp "Install? [Y/n] " answer
        [[ -z "$answer" || "$answer" =~ ^[Yy] ]] && confirmed=true
    fi

    if [ "$confirmed" = true ]; then
        # Use pkexec for graphical sudo, fall back to sudo
        if command -v pkexec &>/dev/null; then
            pkexec apt-get install -y $missing
        else
            sudo apt-get install -y $missing
        fi
    else
        echo "Cannot run without required libraries."
        exit 1
    fi
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
