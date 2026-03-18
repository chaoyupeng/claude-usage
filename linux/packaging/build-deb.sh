#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PKG_NAME="claude-usage"
VERSION="1.1.0"
ARCH="all"
DEB_NAME="${PKG_NAME}_${VERSION}_${ARCH}"

# Create temp staging directory
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "==> Building ${DEB_NAME}.deb"

# --- DEBIAN control ---
mkdir -p "$STAGING/DEBIAN"
cp "$SCRIPT_DIR/DEBIAN/control" "$STAGING/DEBIAN/control"

# --- Python package ---
SITE_PKG="$STAGING/usr/lib/python3/dist-packages/claude_usage"
mkdir -p "$SITE_PKG"
cp "$PROJECT_DIR/claude_usage/"*.py "$SITE_PKG/"

# Copy resources if they exist
if [ -d "$PROJECT_DIR/claude_usage/resources" ] && [ "$(ls -A "$PROJECT_DIR/claude_usage/resources" 2>/dev/null)" ]; then
    mkdir -p "$SITE_PKG/resources"
    cp -r "$PROJECT_DIR/claude_usage/resources/"* "$SITE_PKG/resources/"
fi

# --- Launcher script ---
BIN_DIR="$STAGING/usr/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/$PKG_NAME" << 'LAUNCHER'
#!/usr/bin/env python3 -m claude_usage
LAUNCHER

# --- Desktop entry ---
APPS_DIR="$STAGING/usr/share/applications"
mkdir -p "$APPS_DIR"
cp "$SCRIPT_DIR/claude-usage.desktop" "$APPS_DIR/claude-usage.desktop"

# --- Icon ---
ICON_DIR="$STAGING/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DIR"
if [ -f "$PROJECT_DIR/claude_usage/resources/claude-usage.png" ]; then
    cp "$PROJECT_DIR/claude_usage/resources/claude-usage.png" "$ICON_DIR/claude-usage.png"
else
    echo "WARNING: Icon not found at claude_usage/resources/claude-usage.png"
fi

# --- Permissions ---
find "$STAGING/usr" -type f -exec chmod 644 {} +
find "$STAGING/usr" -type d -exec chmod 755 {} +
chmod 755 "$BIN_DIR/$PKG_NAME"

# --- Build .deb ---
OUTPUT_DIR="$PROJECT_DIR"
dpkg-deb --build "$STAGING" "$OUTPUT_DIR/${DEB_NAME}.deb"

echo "==> Package built: $OUTPUT_DIR/${DEB_NAME}.deb"
