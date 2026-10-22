#!/bin/bash
# Project Gravemind Mac Port: installs Halo 2 (MCC) + Project Gravemind under Wine on Apple Silicon.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/drewdrew21b/project-gravemind-mac-port/main/install.sh)"
#
# Everything lives in ~/Games/ProjectGravemind (override with RECLAIMER_HOME). Safe to re-run: finished steps are skipped.
# Options (environment variables):
#   RECLAIMER_MCC_FROM=<dir>    copy existing MCC game files from <dir> instead of downloading them from Steam
#   RECLAIMER_CACHE=<dir>       reuse already-downloaded archives from <dir>
#   RECLAIMER_UPDATE=1          update an existing install without questions (run by the launcher's updater.py):
#                               admin steps use macOS's password dialog instead of sudo
#   RECLAIMER_GUI=1             run by the launcher window's Setup/Upgrade: no Terminal questions, the macOS password
#                               dialog for Rosetta, the Steam QR code and download progress for the window
set -euo pipefail

REPO_RAW=${RECLAIMER_REPO_RAW:-https://raw.githubusercontent.com/drewdrew21b/project-gravemind-mac-port/main}
BASE=${RECLAIMER_HOME:-$HOME/Games/ProjectGravemind}
CACHE=${RECLAIMER_CACHE:-$BASE/downloads}
STEAM_REL="drive_c/Program Files (x86)/Steam"
MCC_REL="$STEAM_REL/steamapps/common/Halo The Master Chief Collection"
MCC_DIR="$BASE/prefix-wine/$MCC_REL"
MCC_APP=976730
MCC_DEPOTS="976731 976735 976736 976737"  # MCC shared files + Halo 2 campaign + both multiplayer depots

# name|url|sha256
WINE_PKG="wine-staging-11.18-osx64.tar.xz|https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.18/wine-staging-11.18-osx64.tar.xz|b63704b91af269bc026a87f12bd297c4a50caaf570c322e600b6621ef918f127"
DXVK_PKG="dxvk-macOS-async-v1.10.3-20230507-repack.tar.gz|https://github.com/Gcenx/DXVK-macOS/releases/download/v1.10.3-20230507-repack/dxvk-macOS-async-v1.10.3-20230507-repack.tar.gz|acd1520ad105d8ef124a09c8e11a259a5dc8bdc565ad18e0e52693f9807b2477"
MOLTENVK_PKG="MoltenVK-macos-1.4.2.tar|https://github.com/KhronosGroup/MoltenVK/releases/download/v1.4.2/MoltenVK-macos.tar|f95765a6229cb7b915990a2890ce12ebe36a730b021545d3d52ae69ce4c4024e"
DEPOT_PKG="DepotDownloader-macos-arm64.zip|https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_3.4.0/DepotDownloader-macos-arm64.zip|60e80c7c496f3f9a079cd3c62036b35d088c27bc0149baf38f009eb57a52f6a5"
LAUNCHER_SHA=d7533abda6108dfc0026021d5061274babc89bba7fa9a4c1fbfe9a2931c436d4  # launcher/ProjectReclaimer (built by scripts/make_launcher.sh)
UPDATE=${RECLAIMER_UPDATE:-}
GUI=${RECLAIMER_GUI:-}
# give up on a stalled connection instead of hanging (the launcher waits for this when updating)
CURL_LIMITS="--connect-timeout 20 --speed-limit 1024 --speed-time 60 --proto =https --proto-redir =https"

exec 3>&1  # the real output, for error lines from inside $(...) (the window reads them)
STEP=starting
bold() { STEP=$*; printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() {
  printf '\n\033[31mError: %s\033[0m\n' "$*" >&2
  [ -n "$GUI" ] && printf 'error: %s\n' "$*" >&3  # (the window shows this line)
  exit 1
}

fetch() {  # fetch "name|url|sha256" -> path of the verified file in $CACHE
  local name=${1%%|*} rest=${1#*|}; local url=${rest%%|*} sum=${rest##*|} f="$CACHE/${1%%|*}"
  if [ ! -f "$f" ] || [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" != "$sum" ]; then
    note "downloading $name" >&2
    curl -fL $CURL_LIMITS --progress-bar -o "$f.part" "$url" ||
      die "Couldn't download $name. Check your internet connection and try again."
    mv "$f.part" "$f"
  fi
  [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$sum" ] ||
    { rm -f "$f"; die "The download of $name was damaged. Press Try Again to download it again."; }
  printf '%s' "$f"
}

script_file() {  # copy a file from this repo (local checkout or GitHub) to $2
  local here; here=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)
  if [ -n "$here" ] && [ -f "$here/$1" ]; then cp "$here/$1" "$2"; else curl -fsSL $CURL_LIMITS "$REPO_RAW/$1" -o "$2"; fi
}

as_admin() {  # as_admin "<shell command>" "<why>": sudo in Terminal; macOS's password dialog when run by the launcher
  if [ -n "$UPDATE" ] || [ -n "$GUI" ]; then
    local cmd=${1//\\/\\\\}; cmd=${cmd//\"/\\\"}
    local why=${2:-Project Gravemind is changing a system setting.}
    /usr/bin/osascript -e "do shell script \"$cmd\" with prompt \"$why\" with administrator privileges" >/dev/null
  else
    sudo /bin/sh -c "$1" </dev/tty
  fi
}

installed() {  # installed <name> <version>: true when <name> is already installed at <version>
  [ "$(cat "$BASE/.installed/$1" 2>/dev/null)" = "$2" ]
}

mark_installed() { mkdir -p "$BASE/.installed"; printf '%s\n' "$2" > "$BASE/.installed/$1"; }

unlink_documents() {  # give a prefix its own Documents folder instead of Wine's link to ~/Documents
  local d
  for d in "$1"/drive_c/users/*/Documents; do
    [ -L "$d" ] && { rm "$d"; mkdir -p "$d"; }
  done
  return 0
}

halo2_campaign_present() {
  [ -n "$(find "$MCC_DIR/halo2/preload/paks" -name '*.pck' -print -quit 2>/dev/null)" ]
}

halo2_multiplayer_present() {
  [ -f "$MCC_DIR/halo2/h2_maps_win64_dx11/ascension.map" ]
}

halo2_files_present() { halo2_campaign_present && halo2_multiplayer_present; }

# ---------------------------------------------------------------------------------------------------------------
bold "Project Gravemind Mac Port"
note "Installs into: $BASE"
[ "$(uname -m)" = arm64 ] || die "This needs an Apple Silicon Mac (M1 or newer)."
MACOS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
[ "$MACOS_MAJOR" -ge 14 ] || die "This needs macOS 14 Sonoma or newer."
# every helper script runs on Apple's /usr/bin/python3 (part of the developer tools). With Xcode installed but its
# license not accepted it refuses to start, and the install used to fail much later as "check your internet" (#10)
if ! PY_OUT=$("${RECLAIMER_TEST_PYTHON:-/usr/bin/python3}" -c pass 2>&1); then
  case "$PY_OUT" in
    *"xcodebuild -license"*|*"Xcode license"*)
      die "Xcode's license hasn't been accepted, so the helper scripts can't run. Run this in Terminal (it asks for your Mac password), then run the installer again:  sudo xcodebuild -license accept" ;;
    *) die "Apple's developer tools are needed. Run this in Terminal, then run the installer again:  xcode-select --install" ;;
  esac
fi
FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
NEED_GB=82
if halo2_campaign_present && ! halo2_multiplayer_present; then NEED_GB=34
elif halo2_multiplayer_present && ! halo2_campaign_present; then NEED_GB=36
fi
# Partial installs need only the missing Halo 2 component; a fresh install needs all depots plus scratch space.
[ "$FREE_GB" -ge "$NEED_GB" ] || [ -n "${RECLAIMER_MCC_FROM:-}" ] || [ -n "$UPDATE" ] ||
  halo2_files_present ||
  die "Need about $NEED_GB GB free disk space (have ${FREE_GB} GB)."
mkdir -p "$BASE"/{game,tools,logs} "$CACHE"
chmod 700 "$BASE"  # (other accounts on this Mac can look into the home folder: the Steam login and logs stay private)
if [ -n "$GUI" ]; then
  # anything failing without its own message still tells the window which step it was
  trap 'printf "error: Something went wrong at the step “%s”. Check your internet connection and disk space, then press Try Again.\n" "$STEP" >&3' ERR
  # a first install in progress: if it stops, the window offers Setup again (not the 1.0 Upgrade)
  [ -f "$BASE/version" ] || halo2_files_present || touch "$BASE/.setup-incomplete"
fi

if ! /usr/bin/pgrep -q oahd; then
  bold "Installing Rosetta 2 (runs Intel Windows code on Apple Silicon)"
  if [ -n "$GUI" ]; then
    as_admin "softwareupdate --install-rosetta --agree-to-license" \
      "Project Gravemind needs Rosetta, Apple's translator for Intel apps." ||
      die "Rosetta (Apple's Intel translator) didn't install. If you cancelled the password box, press Try Again."
  else
    softwareupdate --install-rosetta --agree-to-license || die "Rosetta install failed."
  fi
fi

bold "Wine (Gcenx Wine Staging 11.18) with MoltenVK 1.4.2"
if [ ! -x "$BASE/wine/Wine Staging.app/Contents/Resources/wine/bin/wine" ]; then
  mkdir -p "$BASE/wine"; tar -xf "$(fetch "$WINE_PKG")" -C "$BASE/wine"
fi
# Wine bundles MoltenVK 1.4.0; 1.4.2 fixes device-loss / argument-buffer bugs behind a GPU address fault seen on
# heavy modded maps, and used ~25% less GPU at the menu
MVK_LIB="$BASE/wine/Wine Staging.app/Contents/Resources/wine/lib/libMoltenVK.dylib"
# (grep -c reads everything: an early-exiting grep SIGPIPEs strings, and under pipefail the check always failed)
if [ "$(strings "$MVK_LIB" | grep -cx '1.4.2')" = 0 ]; then
  tar -xf "$(fetch "$MOLTENVK_PKG")" -C "$CACHE" MoltenVK/MoltenVK/dynamic/dylib/macOS/libMoltenVK.dylib
  # replace, don't overwrite in place: macOS caches a signed library's code signature per file, and Rosetta then
  # refuses the rewritten file ("Attachment of code signature supplement failed")
  rm -f "$MVK_LIB"
  cp "$CACHE/MoltenVK/MoltenVK/dynamic/dylib/macOS/libMoltenVK.dylib" "$MVK_LIB"
fi
note "ok"

bold "Game scripts and Steam downloader helper"
for f in run.sh launch.sh gamecontrollerdb.txt game_process.py workshop_helper.py updater.py tools.py; do
  script_file "scripts/$f" "$BASE/game/$f"
done
chmod +x "$BASE/game/run.sh" "$BASE/game/launch.sh" "$BASE/game/workshop_helper.py" "$BASE/game/updater.py" \
  "$BASE/game/tools.py"
note "ok"

bold "Project Gravemind (latest release, checksum-verified)"
# updater.py verifies the GitHub-published SHA-256 digest before installing the release ZIP.
RECLAIMER_HOME="$BASE" /usr/bin/python3 -I "$BASE/game/updater.py" game 2>>"$BASE/logs/launcher.log" |
  awk '!/^progress: / {sub(/^(status|done|error|offline): /, ""); print "    " $0; fflush()}' ||
  die "Could not install Project Gravemind. Check your internet connection and run the installer again."
[ -f "$BASE/game/gravemind/h2gravemind.exe" ] ||
  die "Could not download Project Gravemind. Check your internet connection and run the installer again."

bold "Windows environment for the Wine version"
WINE_BIN="$BASE/wine/Wine Staging.app/Contents/Resources/wine/bin"
if [ ! -f "$BASE/prefix-wine/system.reg" ]; then
  # (mscoree/mshtml off: no Wine Mono/Gecko install dialogs; the game doesn't use them)
  WINEPREFIX="$BASE/prefix-wine" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=" "$WINE_BIN/wine" wineboot -i >/dev/null 2>&1 || true
  WINEPREFIX="$BASE/prefix-wine" WINEDEBUG=-all "$WINE_BIN/wineserver" -w
fi
# controllers come to the game from SDL. For PlayStation pads Wine otherwise drops SDL's gamepad for a raw PS device
# ("hidraw"), which the game can't use: "no gamepad detected" (#17). Xbox and other pads come from SDL either way.
if ! grep -q '"DisableHidraw"=dword:00000001' "$BASE/prefix-wine/system.reg" 2>/dev/null; then
  WINEPREFIX="$BASE/prefix-wine" WINEDEBUG=-all "$WINE_BIN/wine" reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
    /v DisableHidraw /t REG_DWORD /d 1 /f >/dev/null 2>&1 || true
  WINEPREFIX="$BASE/prefix-wine" WINEDEBUG=-all "$WINE_BIN/wineserver" -w
fi
unlink_documents "$BASE/prefix-wine"
# DXVK-macOS goes into this prefix's system32 so the shared game folder stays free of graphics DLLs.
SYS32="$BASE/prefix-wine/drive_c/windows/system32"
if ! installed dxvk "${DXVK_PKG%%|*}" || [ ! -f "$SYS32/d3d11.dll" ]; then
  tar -xzf "$(fetch "$DXVK_PKG")" -C "$CACHE"
  cp "$CACHE/dxvk-macOS-async-v1.10.3-20230507-repack/x64/d3d10core.dll" "$SYS32/"
  cp "$CACHE/dxvk-macOS-async-v1.10.3-20230507-repack/x64/d3d11.dll" "$SYS32/d3d11.dll"
  mark_installed dxvk "${DXVK_PKG%%|*}"
fi
rm -f "$SYS32/d3d11_dxvk.dll"
note "ok"

bold "DepotDownloader (downloads your game files from Steam)"
if [ ! -x "$BASE/tools/DepotDownloader" ]; then
  unzip -oq "$(fetch "$DEPOT_PKG")" -d "$BASE/tools"; chmod +x "$BASE/tools/DepotDownloader"
fi
note "ok"

bold "Halo 2 game files (your Steam copy of Halo: The Master Chief Collection)"
if halo2_files_present; then
  note "already installed"
elif [ -n "$UPDATE" ]; then
  note "Halo 2 campaign or multiplayer files are incomplete; repair them from Tools after this update."
elif [ -n "${RECLAIMER_MCC_FROM:-}" ]; then
  mkdir -p "$(dirname "$MCC_DIR")"; cp -cR "$RECLAIMER_MCC_FROM" "$MCC_DIR" 2>/dev/null || cp -R "$RECLAIMER_MCC_FROM" "$MCC_DIR"
  note "copied from $RECLAIMER_MCC_FROM"
elif [ -n "$GUI" ]; then
  RECLAIMER_HOME="$BASE" /usr/bin/python3 -I "$BASE/game/workshop_helper.py" game-download "$MCC_DIR" \
    2>>"$BASE/logs/launcher.log" ||
    exit 1  # (it printed the reason)
  halo2_files_present || die "Halo 2 campaign or multiplayer files are missing after the download. Try again to resume."
else
  note "You need to own Halo: The Master Chief Collection on Steam."
  note "A QR code will appear: open the Steam app on your phone > Steam Guard / sign-in QR and scan it."
  note "Halo 2 campaign and multiplayer files are downloaded from your Steam account (~78 GB, including MCC shared files)."
  read -r -p "    Press Return to continue..." _ </dev/tty
  mkdir -p "$MCC_DIR"
  # shellcheck disable=SC2086
  "$BASE/tools/DepotDownloader" -app $MCC_APP -depot $MCC_DEPOTS -os windows -qr -remember-password \
    -dir "$MCC_DIR" -validate </dev/tty || die "Steam download failed. Re-run the installer to resume."
  halo2_files_present || die "Halo 2 campaign or multiplayer files are missing after the download. Re-run the installer to resume."
fi
halo2_files_present || die "The MCC folder needs Halo 2 campaign and multiplayer files. Check your Steam DLC selection and try again."
mkdir -p "$BASE/prefix-wine/$STEAM_REL/steamapps/workshop/content/$MCC_APP"

bold "Launcher app"
script_file launcher/ProjectReclaimer "$CACHE/launcher"
[ "$(shasum -a 256 "$CACHE/launcher" | cut -d' ' -f1)" = "$LAUNCHER_SHA" ] || die "checksum mismatch for the launcher"
# replace, don't overwrite in place: the old launcher may be running (and macOS caches a binary's signature per file)
rm -f "$BASE/tools/ProjectReclaimer"
mv "$CACHE/launcher" "$BASE/tools/ProjectReclaimer"
chmod +x "$BASE/tools/ProjectReclaimer"
mkdir -p "${RECLAIMER_APPS_DIR:-$HOME/Applications}"
script_file scripts/make_app.sh "$BASE/tools/make_app.sh"
# the version the launcher's updater asked for (it checks this afterwards), else this copy's own
if [ -n "${RECLAIMER_EXPECT_VERSION:-}" ]; then echo "$RECLAIMER_EXPECT_VERSION" > "$CACHE/VERSION"
else script_file VERSION "$CACHE/VERSION"; fi
script_file launcher/Resources/AppIcon.icns "$BASE/tools/AppIcon.icns"
/bin/bash "$BASE/tools/make_app.sh" "Project Gravemind" "$(cat "$CACHE/VERSION")"
rm -rf "$CACHE/dxvk-macOS-async-v1.10.3-20230507-repack" "$CACHE/MoltenVK"
# last: the launcher compares this with GitHub's VERSION, so a failed update is tried again next launch
mv "$CACHE/VERSION" "$BASE/version"
rm -f "$BASE/.setup-incomplete"
# the downloaded archives (~1 GB) aren't needed any more, unless they're a cache the caller asked to keep
[ -z "${RECLAIMER_CACHE:-}" ] && rm -rf "$CACHE"
[ -n "$UPDATE" ] && { bold "Updated to $(cat "$BASE/version")"; exit 0; }

bold "Done"
note "Open \"Project Gravemind\" from Spotlight, Launchpad or ~/Applications."
note "It keeps itself and Project Gravemind up to date."
