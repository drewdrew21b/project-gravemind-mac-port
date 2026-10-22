#!/bin/bash
# Remove Project Gravemind Mac Port: apps and ~/Games/ProjectGravemind (game files and Wine).
#   RECLAIMER_YES=1           don't ask for confirmation
set -euo pipefail
BASE=${RECLAIMER_HOME:-$HOME/Games/ProjectGravemind}
APPS=${RECLAIMER_APPS_DIR:-$HOME/Applications}

echo "This deletes $BASE (including Halo 2's game files)"
echo "and Project Gravemind.app in $APPS."
if [ -z "${RECLAIMER_YES:-}" ]; then
  read -r -p "Continue? [y/N] " a </dev/tty
  [[ "$a" =~ ^[Yy] ]] || exit 0
fi

# rm -rf below: only a folder that is an install (RECLAIMER_HOME=~ must never delete the home folder)
if [ "$BASE" = / ] || [ "$BASE" = "$HOME" ] || { [ ! -d "$BASE/game" ] && [ ! -d "$BASE/prefix-wine" ]; }; then
  echo "$BASE doesn't look like a Project Gravemind install, so nothing was removed." >&2
  exit 1
fi
if [ -x "$BASE/game/tools.py" ]; then
  result=$(RECLAIMER_HOME="$BASE" /usr/bin/python3 -I "$BASE/game/tools.py" force-quit)
  if [ "$result" != "ok" ]; then
    echo "The game could not be stopped. Close it and try again." >&2
    exit 1
  fi
fi
pkill -f "$BASE/game/workshop_helper.py" 2>/dev/null || true
pkill -f "$APPS/Project Gravemind.app/Contents/MacOS/ProjectReclaimer" 2>/dev/null || true
rm -rf "$APPS/Project Gravemind.app" "$BASE"
echo "Done."
