#!/bin/sh
#
# run_monitors.sh
#
# Starts jobs.py and app.py at the same time, in the background, and keeps
# them running. If either one dies, its exit is logged and the script keeps
# watching the other. Ctrl+C (or a kill signal) stops both cleanly.
#
# Usage:
#   ./run_monitors.sh
#   ./run_monitors.sh --s      

# Resolve the directory this script lives in, so it can be run from anywhere.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

JOBS_PY="$SCRIPT_DIR/jobs.py"
APP_PY="$SCRIPT_DIR/app.py"

JOBS_LOG="$SCRIPT_DIR/jobs_runner.log"
APP_LOG="$SCRIPT_DIR/app_runner.log"

# Set the full path to your python3 interpreter here.
PYTHON_BIN="set your path"


# Any extra args passed to this script (e.g. --s) are forwarded to jobs.py.
# The ${1+"$@"} form (instead of plain "$@") avoids "Parameter @ is not set"
# errors on strict POSIX shells (e.g. IBM i PASE sh) when no args are given.
JOBS_ARGS=${1+"$@"}

JOBS_PID=""
APP_PID=""

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1"
}

cleanup() {
    log "Stopping monitors..."
    if [ -n "$JOBS_PID" ]; then
        if kill -0 "$JOBS_PID" 2>/dev/null; then
            kill "$JOBS_PID" 2>/dev/null
        fi
    fi
    if [ -n "$APP_PID" ]; then
        if kill -0 "$APP_PID" 2>/dev/null; then
            kill "$APP_PID" 2>/dev/null
        fi
    fi
    wait "$JOBS_PID" "$APP_PID" 2>/dev/null
    log "All monitors stopped."
    exit 0
}

trap cleanup INT TERM

if [ ! -f "$JOBS_PY" ]; then
    log "ERROR: $JOBS_PY not found."
    exit 1
fi
if [ ! -f "$APP_PY" ]; then
    log "ERROR: $APP_PY not found."
    exit 1
fi

log "Starting jobs.py..."
"$PYTHON_BIN" "$JOBS_PY" $JOBS_ARGS >> "$JOBS_LOG" 2>&1 &
JOBS_PID=$!
log "jobs.py started (PID $JOBS_PID), logging to $JOBS_LOG"

log "Starting app.py..."
"$PYTHON_BIN" "$APP_PY" >> "$APP_LOG" 2>&1 &
APP_PID=$!
log "app.py started (PID $APP_PID), logging to $APP_LOG"

# Wait for both; if one exits, note it and keep waiting on the other so the
# script doesn't quit the moment a single process ends.
while [ -n "$JOBS_PID" -o -n "$APP_PID" ]; do
    if [ -n "$JOBS_PID" ]; then
        if kill -0 "$JOBS_PID" 2>/dev/null; then
            : # still running
        else
            log "jobs.py (PID $JOBS_PID) has stopped."
            JOBS_PID=""
        fi
    fi
    if [ -n "$APP_PID" ]; then
        if kill -0 "$APP_PID" 2>/dev/null; then
            : # still running
        else
            log "app.py (PID $APP_PID) has stopped."
            APP_PID=""
        fi
    fi
    sleep 2
done

log "Both processes have exited. Runner finished."