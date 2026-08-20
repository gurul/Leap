#!/usr/bin/env bash
# install-menubar-app.sh — build (or repair) ~/Applications/Leap Menubar.app,
# the wrapper that runs the menu bar switch and owns its macOS permissions.
#
#   scripts/install-menubar-app.sh            build/refresh the app
#   scripts/install-menubar-app.sh --restart  ... and relaunch it
#
# The wrapper is not decoration. macOS attributes Camera/Accessibility grants
# to the responsible *app bundle*, and the session the menu starts is a
# grandchild of this one — so the bundle is what System Settings lists, and the
# bundle's Info.plist must declare NSCameraUsageDescription. Without that key
# macOS refuses the camera request instead of prompting, and "Turn on" starts a
# session that opens a camera which never delivers a frame (2026-08-20).
#
# Editing the bundle changes its ad-hoc signature, which invalidates existing
# TCC grants: after running this, expect to approve Camera (and Accessibility)
# once more.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.venv/bin/leapinput-menubar"
APP="${LEAPINPUT_APP:-$HOME/Applications/Leap Menubar.app}"
ID="world.era.leapinput.menubar"

[ -x "$BIN" ] || { echo "missing $BIN — run scripts/setup.sh first" >&2; exit 1; }

mkdir -p "$APP/Contents/MacOS"

# LSUIElement: menu bar only, no Dock tile. The usage strings are the whole
# point of the bundle — see the header.
cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Leap Menubar</string>
    <key>CFBundleIdentifier</key>
    <string>$ID</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>leap-menubar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSCameraUsageDescription</key>
    <string>Leap Input reads your camera to track your hands and drive the cursor.</string>
</dict>
</plist>
PLIST

src="$(mktemp -t leap-menubar-launcher).c"
sed "s|@BIN@|$BIN|" "$ROOT/scripts/menubar-launcher.c" >"$src"
clang -O2 -o "$APP/Contents/MacOS/leap-menubar" "$src"
rm -f "$src"

# Ad-hoc: enough for a stable TCC identity on a machine-local app; there is no
# Developer ID to sign with and none is needed for a personal login item.
codesign --force --sign - "$APP"
echo "built $APP"

if [ "${1:-}" = "--restart" ]; then
  pkill -f "$APP/Contents/MacOS/leap-menubar" 2>/dev/null || true
  pkill -f "$BIN" 2>/dev/null || true
  sleep 1
  open -a "$APP"
  echo "relaunched — grant Camera when the prompt appears on the first 'Turn on'"
fi

cat <<'NOTE'

Start at login: System Settings > General > Login Items > "+" and pick the app
(already set up if "Leap Menubar" is listed there).
NOTE
