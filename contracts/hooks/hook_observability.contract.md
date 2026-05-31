# Contract: Hook — Observability Process Lifecycle

| Field | Value |
|-------|-------|
| contract_id | HC-OBSERVABILITY |
| hook_name | Observability Process Lifecycle |
| event | session_start, stop |
| version | 1.0.0 |

## Purpose

Manages local telemetry infrastructure processes (OpenTelemetry Collector and Prometheus) around the orchestrator pipeline lifecycle. Ensures telemetry backends are running when the pipeline starts and cleanly stopped when it ends.

## Key Outcomes

1. **[OUTCOME-START]** — On `SessionStart`, ensure OTel Collector and Prometheus are running; start them if not
2. **[OUTCOME-HEALTH]** — Verify backends are healthy via HTTP health-check endpoints before proceeding
3. **[OUTCOME-STOP]** — On `Stop`, gracefully shut down telemetry backends if no other pipeline is active
4. **[OUTCOME-IDEMPOTENT]** — Starting already-running processes is a no-op; stopping already-stopped processes is safe
5. **[OUTCOME-PERSIST]** — PID files and logs persist across hook invocations for process tracking

## Trigger Conditions

| Event | When Fired | Action |
|-------|------------|--------|
| `SessionStart` | Orchestrator pipeline begins | Start OTel Collector + Prometheus if not already running |
| `Stop` | Pipeline ends or user closes session | Stop processes if no active pipelines remain |

## Infrastructure Requirements

### Binaries

| Binary | Purpose | Source | Install |
|--------|---------|--------|---------|
| `otelcol-contrib` | OpenTelemetry Collector | GitHub Releases (open-telemetry/opentelemetry-collector-releases) | `scripts/install-observability.sh` |
| `prometheus` | Metrics storage and query | GitHub Releases (prometheus/prometheus) | `scripts/install-observability.sh` |

Binaries are installed to `<project_root>/observability/.bin/` — no sudo required.

### Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `otel-collector-config.yml` | OTel Collector pipeline config (receivers, processors, exporters) | `observability/otel-collector-config.yml` |
| `prometheus.yml` | Prometheus scrape config (scrape OTel Collector metrics endpoint) | `observability/prometheus/prometheus.yml` |

### Directory Structure

```
<project_root>/observability/
├── .bin/                    ← Downloaded binaries (gitignored)
│   ├── otelcol-contrib
│   └── prometheus
├── .pids/                   ← PID files for running processes
├── .logs/                   ← Process logs and hook logs
├── .prom-data/              ← Prometheus data directory
├── .hook-state/             ← Hook state files
├── otel-collector-config.yml
├── prometheus/
│   └── prometheus.yml
└── .gitignore               ← Ignores .bin/, .pids/, .logs/, .prom-data/
```

## Workflow Logic

### SessionStart Flow

1. Create required directories (`.pids/`, `.logs/`, `.prom-data/`, `.hook-state/`)
2. Check if `otelcol-contrib` binary exists at `observability/.bin/otelcol-contrib`
   - If missing → run `scripts/install-observability.sh --check` to report status
   - If missing → exit with warning (non-blocking), telemetry degraded
3. Check if processes are already running via PID files
   - If running → verify health via HTTP endpoints → no-op if healthy
   - If stale PID → clean up PID file, restart
4. Start OTel Collector:
   - Bind to `localhost:4317` (gRPC), `localhost:4318` (HTTP), `localhost:13133` (health)
   - Config: `observability/otel-collector-config.yml`
   - Log to: `observability/.logs/otelcol.log`
   - Write PID to: `observability/.pids/otelcol.pid`
5. Start Prometheus:
   - Bind to `localhost:9090`
   - Config: `observability/prometheus/prometheus.yml`
   - Data dir: `observability/.prom-data/`
   - Log to: `observability/.logs/prometheus.log`
   - Write PID to: `observability/.pids/prometheus.pid`
6. Health check both endpoints (retry up to 3 times with 2s delay)
7. Record success/failure state in `observability/.hook-state/`

### Stop Flow

1. Check if any other pipeline is still active (via `observability/.hook-state/active_feature_id`)
   - If active pipeline exists → do NOT stop processes
2. Read PID files
3. Send `SIGTERM` to each process
4. Wait up to 5 seconds for graceful shutdown
5. If still running after timeout → send `SIGKILL`
6. Remove PID files
7. Clean up hook state files

## Exit Codes

| Code | Meaning | Agent Behavior |
|------|---------|----------------|
| `0` | Processes managed successfully | Pipeline proceeds |
| `1` | Warning — telemetry degraded (binary missing, health check failed) | Pipeline proceeds without telemetry |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| OTel Collector port | `otel-collector-config.yml` | `4317` (gRPC), `4318` (HTTP) |
| Prometheus port | `prometheus/prometheus.yml` | `9090` |
| Binary install path | `scripts/install-observability.sh` | `observability/.bin/` |
| Log retention | Hook config | 3 most recent runs |
| Health check timeout | Hook config | 3 retries × 2s |
| Stale PID age | Hook config | 300 seconds |
