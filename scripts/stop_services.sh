#!/usr/bin/env bash
# Stop services started by start_services.sh using pidfiles
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
RUN_DIR="$ROOT_DIR/run"
LOG_DIR="$ROOT_DIR/logs"

if [ ! -d "$RUN_DIR" ]; then
  echo "No run directory found, nothing to stop"
  exit 0
fi

stopped=0
for pidfile in "$RUN_DIR"/*.pid; do
  [ -e "$pidfile" ] || continue
  svc=$$(basename "$pidfile" .pid)
  pid=$$(cat "$pidfile" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "Stopping $svc (pid $pid)"
    kill "$pid"
    sleep 0.5
    if kill -0 "$pid" 2>/dev/null; then
      echo "PID $pid still alive, sending SIGKILL"
      kill -9 "$pid" || true
    fi
    stopped=1
  else
    echo "$svc not running (stale pidfile), removing pidfile"
  fi
  rm -f "$pidfile"
done

if [ $stopped -eq 0 ]; then
  echo "No running services found."
else
  echo "Requested services stopped."
fi
