#!/usr/bin/env bash
###############################################################################
# start.sh — Start the Copilot Agents observability stack (local processes)
#
# Starts otel-collector and prometheus as background processes.
# PID files are stored in .github/observability/.pids/
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBS_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$OBS_DIR/.pids"
LOG_DIR="$OBS_DIR/.logs"
PROM_DATA_DIR="$OBS_DIR/.prom-data"

mkdir -p "$PID_DIR" "$LOG_DIR" "$PROM_DATA_DIR"

echo "========================================"
echo " Copilot Agents — Observability Stack"
echo "========================================"
echo ""

# ─── Check prerequisites ─────────────────────────────────────────────────────

check_binary() {
  local name="$1"
  local install_hint="$2"
  if ! command -v "$name" &>/dev/null; then
    echo "ERROR: $name is not installed."
    echo "Install with: $install_hint"
    exit 1
  fi
}

check_binary "otelcol-contrib" "brew install open-telemetry/opentelemetry-collector/opentelemetry-collector-contrib"
check_binary "prometheus" "brew install prometheus"

# ─── Check if already running ────────────────────────────────────────────────

is_running() {
  local pidfile="$PID_DIR/$1.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    # Stale PID file
    rm -f "$pidfile"
  fi
  return 1
}

# ─── Start OTel Collector ────────────────────────────────────────────────────

if is_running "otelcol"; then
  echo "  ✓ OTel Collector already running (PID $(cat "$PID_DIR/otelcol.pid"))"
else
  echo "  Starting OTel Collector..."
  otelcol-contrib --config="$OBS_DIR/otel-collector-config.yml" \
    > "$LOG_DIR/otelcol.log" 2>&1 &
  echo $! > "$PID_DIR/otelcol.pid"
  echo "  ✓ OTel Collector started (PID $!)"
fi

# ─── Start Prometheus ────────────────────────────────────────────────────────

if is_running "prometheus"; then
  echo "  ✓ Prometheus already running (PID $(cat "$PID_DIR/prometheus.pid"))"
else
  echo "  Starting Prometheus..."
  prometheus \
    --config.file="$OBS_DIR/prometheus/prometheus.yml" \
    --storage.tsdb.path="$PROM_DATA_DIR" \
    --web.listen-address=":9090" \
    --storage.tsdb.retention.time=7d \
    > "$LOG_DIR/prometheus.log" 2>&1 &
  echo $! > "$PID_DIR/prometheus.pid"
  echo "  ✓ Prometheus started (PID $!)"
fi

# ─── Health checks ───────────────────────────────────────────────────────────

echo ""
echo "Waiting for services to be ready..."
sleep 3

check_service() {
  local name="$1"
  local url="$2"
  if curl -sf "$url" > /dev/null 2>&1; then
    echo "  ✓ $name is ready"
    return 0
  else
    echo "  ✗ $name is not yet ready"
    return 1
  fi
}

check_service "OTel Collector" "http://localhost:13133" || true
check_service "Prometheus" "http://localhost:9090/-/ready" || true

echo ""
echo "Service URLs:"
echo "  Prometheus   →  http://localhost:9090"
echo "  OTel gRPC    →  localhost:4317"
echo "  OTel HTTP    →  http://localhost:4318"
echo ""
echo "Logs: $LOG_DIR/"
echo ""
