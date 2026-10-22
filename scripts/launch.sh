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
exec "$RECLAIMER_HOME/game/run.sh" > "$RECLAIMER_LOG" 2>&1
