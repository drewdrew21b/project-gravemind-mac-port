#!/bin/bash
# make_app.sh "<App Name>" <version>: build ~/Applications/<App Name>.app around the launcher window
# ($RECLAIMER_HOME/tools/ProjectReclaimer, installed by install.sh). Safe to run while the app is open.
set -euo pipefail
NAME=$1 VERSION=${2:-0}
BASE=${RECLAIMER_HOME:-$HOME/Games/ProjectGravemind}
APP="${RECLAIMER_APPS_DIR:-$HOME/Applications}/$NAME.app"
# an update rebuilds the app the player opened, wherever they moved it (the launcher passes its own path)
case "${RECLAIMER_APP_PATH:-}" in *.app) [ -d "$RECLAIMER_APP_PATH" ] && APP=$RECLAIMER_APP_PATH ;; esac
xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<< "$1"; }
ID=local.projectgravemind.$(echo "$NAME" | tr 'A-Z ' 'a-z-')
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# (older versions started the game from a shell script named "launch")
rm -f "$APP/Contents/MacOS/launch" "$APP/Contents/MacOS/ProjectReclaimer"
cp "$BASE/tools/ProjectReclaimer" "$APP/Contents/MacOS/ProjectReclaimer"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$(xml "$NAME")</string>
  <key>CFBundleDisplayName</key><string>$(xml "$NAME")</string>
  <key>CFBundleIdentifier</key><string>$ID</string>
  <key>CFBundleExecutable</key><string>ProjectReclaimer</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
  <key>NSMicrophoneUsageDescription</key><string>Project Gravemind uses your microphone for in-game voice chat.</string>
  <key>ReclaimerHome</key><string>$(xml "$BASE")</string>
</dict>
</plist>
PLIST

if [ -f "$BASE/tools/AppIcon.icns" ]; then
  cp "$BASE/tools/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
fi
# ad-hoc signature over the whole bundle, so macOS treats the binary, Info.plist and icon as one app
codesign --force --sign - "$APP" 2>/dev/null || true
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" || true
echo "    $APP"
