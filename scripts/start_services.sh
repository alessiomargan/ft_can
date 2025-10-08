#!/usr/bin/env bash
# Start broker, async_pub, async_sub, and dashboard with pidfiles and logs
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/run"
mkdir -p "$LOG_DIR" "$RUN_DIR"
CONDA_ACTIVATE="source $(conda info --base)/etc/profile.d/conda.sh && conda activate ft-can"

# If FORCE=1 is set in the environment, ignore/remove existing pidfiles and start services anyway
FORCE=${FORCE:-0}

start_service() {
  name=$1
  shift
  cmd="$@"
  pidfile="$RUN_DIR/${name}.pid"
  logfile="$LOG_DIR/${name}.log"
  if [ -f "$pidfile" ]; then
    if [ "$FORCE" = "1" ]; then
      echo "FORCE=1: removing existing pidfile for $name -> $pidfile"
      rm -f "$pidfile"
    else
      pid=$(cat "$pidfile" 2>/dev/null || echo "")
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "$name already running (pid $pid), skipping"
        return
      else
        echo "Stale pidfile for $name, removing"
        rm -f "$pidfile"
      fi
    fi
  fi
  echo "Starting $name -> $logfile"
  bash -c "$CONDA_ACTIVATE && nohup $cmd >> \"$logfile\" 2>&1 & echo \$! > \"$pidfile\""
}

# Start broker first
start_service zmq_broker python "$ROOT_DIR/zmq_broker.py"
# small delay to let broker bind sockets
sleep 1
start_service async_pub python "$ROOT_DIR/async_pub.py"
sleep 1
start_service async_sub python "$ROOT_DIR/async_sub.py"
sleep 1
start_service dashboard python "$ROOT_DIR/dashboard.py"

echo "All services started. Use 'make status-supervised' to check logs and pids."