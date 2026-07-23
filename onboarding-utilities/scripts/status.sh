#!/usr/bin/env bash
###############################################################################
# status.sh — Check health of the observability stack (local processes)
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBS_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$OBS_DIR/.pids"

echo "========================================"
echo " Observability Stack — Status"
echo "========================================"
echo ""

# Process status
echo "Process status:"
for svc in otelcol prometheus; do
  pidfile="$PID_DIR/$svc.pid"
  if [[ -f "$pidfile" ]]; then
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ✓ $svc — running (PID $pid)"
    else
      echo "  ✗ $svc — dead (stale PID $pid)"
    fi
  else
    echo "  ✗ $svc — not running"
  fi
done
echo ""

# Service health
echo "Service health:"
for svc in \
  "OTel Collector|http://localhost:13133" \
  "Prometheus|http://localhost:9090/-/ready"
do
  name="${svc%%|*}"
  url="${svc##*|}"
  if curl -sf "$url" > /dev/null 2>&1; then
    echo "  ✓ $name — healthy"
  else
    echo "  ✗ $name — unreachable"
  fi
done

echo ""
