#!/usr/bin/env bash
###############################################################################
# stop.sh — Stop the Copilot Agents observability stack (local processes)
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBS_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$OBS_DIR/.pids"

stop_process() {
  local name="$1"
  local pidfile="$PID_DIR/$name.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "  ✓ Stopped $name (PID $pid)"
    else
      echo "  • $name was not running (stale PID)"
    fi
    rm -f "$pidfile"
  else
    echo "  • $name is not running"
  fi
}

echo "Stopping observability stack..."
stop_process "otelcol"
stop_process "prometheus"

echo ""
echo "Stack stopped. Prometheus data preserved in $OBS_DIR/.prom-data/"
echo "To clear data: rm -rf $OBS_DIR/.prom-data/"
echo ""
