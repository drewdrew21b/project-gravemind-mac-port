#!/bin/zsh
# Start Project Gravemind (the launcher window's Play button runs this).
export RECLAIMER_HOME=${RECLAIMER_HOME:-~/Games/ProjectGravemind}
export RECLAIMER_GFX=wine
if [ -z "${RECLAIMER_LOG:-}" ]; then
	if [ "${GRAVEMIND_DEBUG:-}" = 1 ]; then
		RECLAIMER_LOG="$RECLAIMER_HOME/logs/client-wine-debug.log"
	else
		RECLAIMER_LOG="$RECLAIMER_HOME/logs/client-wine.log"
	fi
fi
export RECLAIMER_LOG
mkdir -p "$RECLAIMER_HOME/logs"
: > "$RECLAIMER_LOG"
# Start the helper from the install folder so it can identify this install's game process.
cd "$RECLAIMER_HOME/game" || exit 1
/usr/bin/python3 -I "$RECLAIMER_HOME/game/workshop_helper.py" watch >> "$RECLAIMER_HOME/logs/workshop-helper.log" 2>&1 &
exec "$RECLAIMER_HOME/game/run.sh" > "$RECLAIMER_LOG" 2>&1
