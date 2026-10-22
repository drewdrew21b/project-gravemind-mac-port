#!/bin/zsh
# Start Project Reclaimer with the Workshop mod helper alongside it (the launcher window's Play button runs this).
export RECLAIMER_HOME=${RECLAIMER_HOME:-~/Games/ProjectReclaimer}
export RECLAIMER_GFX=wine RECLAIMER_LOG="$RECLAIMER_HOME/logs/client-wine.log"
mkdir -p "$RECLAIMER_HOME/logs"
: > "$RECLAIMER_LOG"
# (from the game folder: game_process.py counts a process as this install's by its working folder)
cd "$RECLAIMER_HOME/game" || exit 1
/usr/bin/python3 -I "$RECLAIMER_HOME/game/workshop_helper.py" watch >> "$RECLAIMER_HOME/logs/workshop-helper.log" 2>&1 &
exec "$RECLAIMER_HOME/game/run.sh" > "$RECLAIMER_LOG" 2>&1
