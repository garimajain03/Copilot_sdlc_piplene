#!/usr/bin/env bash
###############################################################################
# install-observability.sh — Download OTel Collector & Prometheus binaries
#
# Downloads official release binaries to observability/.bin/ — no sudo required.
#
# Usage:
#   ./scripts/install-observability.sh            # Install both
#   ./scripts/install-observability.sh --check    # Check if installed
#   ./scripts/install-observability.sh --json     # Output status as JSON
#
# Supports: macOS (arm64, amd64), Linux (arm64, amd64)
###############################################################################
set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

OTELCOL_VERSION="${OTELCOL_VERSION:-0.151.0}"
PROMETHEUS_VERSION="${PROMETHEUS_VERSION:-3.4.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$REPO_ROOT/observability/.bin"
OBS_DIR="$REPO_ROOT/observability"

# ─── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✗${NC}  $*" >&2; }

# ─── Platform Detection ──────────────────────────────────────────────────────

detect_platform() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"

  case "$os" in
    darwin) OS="darwin" ;;
    linux)  OS="linux" ;;
    *)      error "Unsupported OS: $os"; exit 1 ;;
  esac

  case "$arch" in
    arm64|aarch64) ARCH="arm64" ;;
    x86_64|amd64)  ARCH="amd64" ;;
    *)             error "Unsupported architecture: $arch"; exit 1 ;;
  esac
}

# ─── Download Helpers ─────────────────────────────────────────────────────────

download() {
  local url="$1" dest="$2"
  info "Downloading: $url"
  if command -v curl &>/dev/null; then
    curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url"
  elif command -v wget &>/dev/null; then
    wget -q -O "$dest" "$url"
  else
    error "Neither curl nor wget found"; exit 1
  fi
}

# ─── Install OTel Collector ──────────────────────────────────────────────────

install_otelcol() {
  if [[ -x "$BIN_DIR/otelcol-contrib" ]]; then
    success "otelcol-contrib already installed"
    return 0
  fi

  info "Installing otelcol-contrib v${OTELCOL_VERSION}..."
  local tmp
  tmp="$(mktemp -d)"
  trap "rm -rf '$tmp'" RETURN

  local archive_name="otelcol-contrib_${OTELCOL_VERSION}_${OS}_${ARCH}.tar.gz"
  local url="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_VERSION}/${archive_name}"

  download "$url" "$tmp/$archive_name"
  tar -xzf "$tmp/$archive_name" -C "$tmp"

  if [[ -f "$tmp/otelcol-contrib" ]]; then
    mv "$tmp/otelcol-contrib" "$BIN_DIR/otelcol-contrib"
  else
    error "otelcol-contrib binary not found in archive"
    return 1
  fi

  chmod +x "$BIN_DIR/otelcol-contrib"
  success "otelcol-contrib v${OTELCOL_VERSION} installed to $BIN_DIR/"
}

# ─── Install Prometheus ───────────────────────────────────────────────────────

install_prometheus() {
  if [[ -x "$BIN_DIR/prometheus" ]]; then
    success "prometheus already installed"
    return 0
  fi

  info "Installing prometheus v${PROMETHEUS_VERSION}..."
  local tmp
  tmp="$(mktemp -d)"
  trap "rm -rf '$tmp'" RETURN

  local archive_name="prometheus-${PROMETHEUS_VERSION}.${OS}-${ARCH}.tar.gz"
  local url="https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/${archive_name}"

  download "$url" "$tmp/$archive_name"
  tar -xzf "$tmp/$archive_name" -C "$tmp"

  local extracted_dir="prometheus-${PROMETHEUS_VERSION}.${OS}-${ARCH}"
  if [[ -f "$tmp/$extracted_dir/prometheus" ]]; then
    mv "$tmp/$extracted_dir/prometheus" "$BIN_DIR/prometheus"
  else
    error "prometheus binary not found in archive"
    return 1
  fi

  chmod +x "$BIN_DIR/prometheus"
  success "prometheus v${PROMETHEUS_VERSION} installed to $BIN_DIR/"
}

# ─── Setup Config Files ──────────────────────────────────────────────────────

setup_configs() {
  # OTel Collector config
  if [[ ! -f "$OBS_DIR/otel-collector-config.yml" ]]; then
    info "Creating default otel-collector-config.yml..."
    cat > "$OBS_DIR/otel-collector-config.yml" << 'OTELCFG'
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "localhost:4317"
      http:
        endpoint: "localhost:4318"

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  prometheus:
    endpoint: "localhost:8889"
    namespace: "copilot"

extensions:
  health_check:
    endpoint: "localhost:13133"

service:
  extensions: [health_check]
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
OTELCFG
    success "Created otel-collector-config.yml"
  fi

  # Prometheus config
  mkdir -p "$OBS_DIR/prometheus"
  if [[ ! -f "$OBS_DIR/prometheus/prometheus.yml" ]]; then
    info "Creating default prometheus.yml..."
    cat > "$OBS_DIR/prometheus/prometheus.yml" << 'PROMCFG'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['localhost:8889']
    scrape_interval: 5s
PROMCFG
    success "Created prometheus.yml"
  fi

  # .gitignore
  if [[ ! -f "$OBS_DIR/.gitignore" ]]; then
    cat > "$OBS_DIR/.gitignore" << 'GITIGNORE'
.bin/
.pids/
.logs/
.prom-data/
.hook-state/
.timestamps/
GITIGNORE
    success "Created observability/.gitignore"
  fi
}

# ─── Check Mode ───────────────────────────────────────────────────────────────

check_status() {
  local otelcol_ok=false prometheus_ok=false
  [[ -x "$BIN_DIR/otelcol-contrib" ]] && otelcol_ok=true
  [[ -x "$BIN_DIR/prometheus" ]] && prometheus_ok=true

  if [[ "$1" == "--json" ]]; then
    cat << EOF
{
  "otelcol_contrib": {"installed": $otelcol_ok, "path": "$BIN_DIR/otelcol-contrib", "version": "$OTELCOL_VERSION"},
  "prometheus": {"installed": $prometheus_ok, "path": "$BIN_DIR/prometheus", "version": "$PROMETHEUS_VERSION"},
  "config_dir": "$OBS_DIR",
  "all_installed": $([ "$otelcol_ok" = true ] && [ "$prometheus_ok" = true ] && echo true || echo false)
}
EOF
  else
    echo ""
    echo "Observability Stack Status:"
    echo "─────────────────────────────"
    if $otelcol_ok; then
      success "otelcol-contrib v${OTELCOL_VERSION}: installed at $BIN_DIR/"
    else
      warn "otelcol-contrib: NOT installed"
    fi
    if $prometheus_ok; then
      success "prometheus v${PROMETHEUS_VERSION}: installed at $BIN_DIR/"
    else
      warn "prometheus: NOT installed"
    fi
    echo ""
  fi

  if $otelcol_ok && $prometheus_ok; then
    return 0
  else
    return 1
  fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
  detect_platform

  case "${1:-install}" in
    --check)
      check_status "--text"
      ;;
    --json)
      check_status "--json"
      ;;
    install|"")
      info "Installing observability stack for ${OS}/${ARCH}..."
      mkdir -p "$BIN_DIR"

      local failed=0
      install_otelcol || { warn "Failed to install otelcol-contrib"; failed=1; }
      install_prometheus || { warn "Failed to install prometheus"; failed=1; }
      setup_configs

      echo ""
      if [[ $failed -eq 0 ]]; then
        success "Observability stack installed successfully!"
        echo "  Binaries: $BIN_DIR/"
        echo "  Configs:  $OBS_DIR/"
      else
        warn "Some components failed to install. Telemetry will run in degraded mode."
      fi
      return $failed
      ;;
    *)
      echo "Usage: $0 [--check|--json]"
      exit 1
      ;;
  esac
}

main "$@"
