#!/bin/bash
# make_dmg.sh [out.dmg]: build Project-Gravemind-Mac-Port.dmg: the Project Gravemind app (the launcher window, which
# installs everything on first open and otherwise opens the installed app), a picture of
# macOS's one-time "Open Anyway" step, and a read-me. The installer/scripts are bundled for reproducible first-run setup.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-dist/Project-Gravemind-Mac-Port.dmg}
STAGE=$(mktemp -d)/"Project Gravemind"
APP="$STAGE/Project Gravemind.app"
swift scripts/make_icon.swift >/dev/null
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$(dirname "$OUT")"

cp launcher/ProjectReclaimer "$APP/Contents/MacOS/ProjectReclaimer"
cp launcher/Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
RESOURCES="$APP/Contents/Resources"
mkdir -p "$RESOURCES/scripts" "$RESOURCES/launcher"
cp install.sh VERSION "$RESOURCES/"
cp launcher/ProjectReclaimer "$RESOURCES/launcher/ProjectReclaimer"
for f in run.sh launch.sh gamecontrollerdb.txt workshop_helper.py updater.py tools.py make_app.sh; do
   cp "scripts/$f" "$RESOURCES/scripts/$f"
done
# no ReclaimerHome key: that marks the installed copy (see LauncherApp.swift), this one installs or hands off
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
   <key>CFBundleName</key><string>Project Gravemind</string>
   <key>CFBundleDisplayName</key><string>Project Gravemind</string>
   <key>CFBundleIdentifier</key><string>local.projectgravemind.setup</string>
  <key>CFBundleExecutable</key><string>ProjectReclaimer</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$(cat VERSION)</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP"

launcher/ProjectReclaimer --render-guide "$STAGE" >/dev/null
mv "$STAGE/guide.png" "$STAGE/How to open it the first time.png"

cat > "$STAGE/Read Me First.txt" <<'TXT'
Project Gravemind for Mac (Halo 2 from Halo: The Master Chief Collection)

You need: an Apple Silicon Mac (M1 or newer) on macOS 14 or newer, Halo: The Master Chief Collection with
Halo 2 on Steam, the Steam app on your phone, and about 82 GB free disk space.

1. Double-click "Project Gravemind".
   The first time, macOS blocks it because it isn't from the App Store. The picture
   "How to open it the first time" shows how to allow it (System Settings > Privacy & Security >
   Open Anyway). You only do this once.
2. The Project Gravemind window installs Wine and downloads Halo 2 campaign, multiplayer, and MCC shared files (~78 GB) from
   your own Steam account. Scan the QR code with the Steam app when asked. macOS may ask for your
   password to install Rosetta.
3. When it's done, it opens Project Gravemind from your Applications folder: press Play. You can eject
   this disk image and move it to the Trash.

The app and Project Gravemind check for updates when opened. Tools can repair or remove Halo 2 files,
force-quit the game, make a diagnostic report, and uninstall the Mac port.
More help: https://github.com/drewdrew21b/project-gravemind-mac-port
TXT

rm -f "$OUT"
hdiutil create -quiet -volname "Project Gravemind" -srcfolder "$STAGE" -fs HFS+ -format UDZO "$OUT"
rm -rf "$(dirname "$STAGE")"
echo "$OUT"
