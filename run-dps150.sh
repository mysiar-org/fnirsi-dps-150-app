#!/usr/bin/env bash
# Launch the DPS-150 control panel with the project's virtualenv.
# Used by dps150.desktop, but can also be run directly.

set -u

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$APP_DIR" || exit 1

PYTHON="$APP_DIR/venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    zenity --error --title="FNIRSI DPS-150" \
        --text="Python virtualenv not found:\n$PYTHON\n\nCreate it with:\n  make venv" 2>/dev/null \
        || echo "ERROR: venv python not found at $PYTHON" >&2
    exit 1
fi

# Log output so failures started from the menu can be inspected.
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/dps150-app.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

exec "$PYTHON" "$APP_DIR/app.py" >>"$LOG" 2>&1
