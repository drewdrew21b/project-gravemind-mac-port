#!/bin/zsh
# Launch Project Gravemind under Wine Staging + DXVK-macOS (D3D11 -> Vulkan -> MoltenVK -> Metal).
BASE=${RECLAIMER_HOME:-~/Games/ProjectGravemind}
if [ "${GRAVEMIND_DEBUG:-}" = 1 ]; then
  export WINEDEBUG=${GRAVEMIND_WINEDEBUG:-+timestamp,+pid,+tid,err+all,+seh,+winsock,+winhttp,+wininet}
  export DXVK_LOG_LEVEL=${DXVK_LOG_LEVEL:-info}
  export DXVK_LOG_PATH=${DXVK_LOG_PATH:-"$BASE/logs"}
else
  export WINEDEBUG=${WINEDEBUG:--all,err+d3d,err+vulkan,err+mmdevapi,err+coreaudio}
  export DXVK_LOG_LEVEL=${DXVK_LOG_LEVEL:-warn}
fi

export WINEPREFIX="$BASE/prefix-wine"
# ~/.zshenv may inject an ARM shim (e.g. libnomallocstacklogging) into every zsh: this script is #!/bin/zsh,
# but Wine runs as an x86_64 (Rosetta) binary that cannot load ARM dylibs and crashes at launch.
unset DYLD_INSERT_LIBRARIES
WINE="$BASE/wine/Wine Staging.app/Contents/Resources/wine/bin/wine"
export WINEDLLOVERRIDES="d3d11,d3d10core=n,b"
export DXVK_ASYNC=1
export MVK_CONFIG_LOG_LEVEL=1

# Controller mappings: bundled database, plus any user calibrations from the launcher
DB="$BASE/game/gamecontrollerdb.txt"
if [ -f "$BASE/controller-mappings.txt" ]; then
  DB="$BASE/controller-mappings-active.txt"
  cat "$BASE/game/gamecontrollerdb.txt" "$BASE/controller-mappings.txt" 2>/dev/null > "$DB"
fi
[ -s "$DB" ] && export SDL_GAMECONTROLLERCONFIG_FILE="$DB"

CHOSEN=$(cat "$BASE/game/chosen-version" 2>/dev/null)
EXE="$BASE/game/gravemind/h2gravemind.exe"
if [ -n "$CHOSEN" ] && [ -f "$BASE/game/versions/v$CHOSEN/h2gravemind.exe" ]; then
  EXE="$BASE/game/versions/v$CHOSEN/h2gravemind.exe"
fi
[ -f "$EXE" ] || { echo "Project Gravemind is not installed in $BASE/game/gravemind" >&2; exit 1; }
cd "$(dirname "$EXE")" || exit 1
exec "$WINE" "$EXE" "$@"
