#!/bin/sh
# Compila la app del Mac y monta LimitBar.app (sin Xcode: basta con las Command Line Tools).
#   scripts/build_app.sh           deja la app en mac/build/LimitBar.app
#   scripts/build_app.sh install   además la copia a /Applications y la abre
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/mac/build/LimitBar.app"

# El sistema nuevo (swiftbuild) falla sin Xcode («Unknown error parsing property list»).
SWIFT_FLAGS="-c release --package-path $REPO/mac --build-system native"
swift build $SWIFT_FLAGS
BIN="$(swift build $SWIFT_FLAGS --show-bin-path 2>/dev/null)/LimitBar"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/LimitBar"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LimitBar</string>
  <key>CFBundleIdentifier</key><string>com.icaraballo.limitbar.app</string>
  <key>CFBundleExecutable</key><string>LimitBar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>LBRepoPath</key><string>$REPO</string>
</dict>
</plist>
EOF
codesign --force --sign - "$APP"
echo "Lista: $APP"

if [ "${1:-}" = "install" ]; then
  pkill -x LimitBar 2>/dev/null || true
  rm -rf /Applications/LimitBar.app
  cp -R "$APP" /Applications/
  open /Applications/LimitBar.app
  echo "Instalada en /Applications y abierta"
fi
