#Requires -Version 5.1
# -----------------------------------------------------------------------------
# install-observability.ps1 - Download OTel Collector and Prometheus binaries (Windows)
#
# Downloads official release binaries to observability/.bin/ - no admin required.
#
# Usage:
#   .\scripts\install-observability.ps1            # Install both
#   .\scripts\install-observability.ps1 -Check     # Check if installed
#   .\scripts\install-observability.ps1 -Json      # Output status as JSON
#
# Supports: Windows (amd64)
# -----------------------------------------------------------------------------

[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

# --- Configuration ------------------------------------------------------------

$OtelcolVersion = if ($env:OTELCOL_VERSION) { $env:OTELCOL_VERSION } else { "0.151.0" }
$PrometheusVersion = if ($env:PROMETHEUS_VERSION) { $env:PROMETHEUS_VERSION } else { "3.4.1" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$BinDir = Join-Path (Join-Path $RepoRoot "observability") ".bin"
$ObsDir = Join-Path $RepoRoot "observability"

# --- Helpers -----------------------------------------------------------------

function Write-Info { param($Message) Write-Host "i  $Message" -ForegroundColor Blue }
function Write-Success { param($Message) Write-Host "v  $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "!  $Message" -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host "x  $Message" -ForegroundColor Red }

# --- Platform Detection ------------------------------------------------------

$Arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "386" }
$OS = "windows"

# --- Download Helper ---------------------------------------------------------

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )
    Write-Info "Downloading: $Url"
    $ProgressPreference = 'SilentlyContinue'
    $retries = 3
    for ($i = 1; $i -le $retries; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
            return
        } catch {
            if ($i -eq $retries) {
                Write-Err "Download failed: $_"
                throw
            }
            Write-Warn "Retry $i/$retries..."
            Start-Sleep -Seconds 2
        }
    }
}

# --- Check Mode --------------------------------------------------------------

$otelcolPath = Join-Path $BinDir "otelcol-contrib.exe"
$prometheusPath = Join-Path $BinDir "prometheus.exe"

if ($Check -or $Json) {
    $otelcolInstalled = Test-Path $otelcolPath
    $prometheusInstalled = Test-Path $prometheusPath

    if ($Json) {
        $status = @{
            otelcol_contrib = @{
                installed = $otelcolInstalled
                path = $otelcolPath
                version = $OtelcolVersion
            }
            prometheus = @{
                installed = $prometheusInstalled
                path = $prometheusPath
                version = $PrometheusVersion
            }
        } | ConvertTo-Json -Depth 3
        Write-Output $status
    } else {
        if ($otelcolInstalled) { Write-Success "otelcol-contrib found at $otelcolPath" }
        else { Write-Warn "otelcol-contrib NOT found" }

        if ($prometheusInstalled) { Write-Success "prometheus found at $prometheusPath" }
        else { Write-Warn "prometheus NOT found" }
    }

    if ($otelcolInstalled -and $prometheusInstalled) { exit 0 }
    else { exit 1 }
}

# --- Install -----------------------------------------------------------------

Write-Info "Installing observability binaries for Windows ($Arch)..."

# Create directories
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".pids") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".prom-data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".hook-state") | Out-Null

# --- Install OTel Collector --------------------------------------------------

if (-not (Test-Path $otelcolPath)) {
    $otelcolUrl = "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OtelcolVersion}/otelcol-contrib_${OtelcolVersion}_${OS}_${Arch}.tar.gz"
    $otelcolArchive = Join-Path $env:TEMP "otelcol-contrib.tar.gz"

    Download-File -Url $otelcolUrl -Destination $otelcolArchive

    Write-Info "Extracting otelcol-contrib..."
    tar -xzf $otelcolArchive -C $BinDir "otelcol-contrib.exe" 2>$null
    if (-not (Test-Path $otelcolPath)) {
        # Fallback: extract everything and find the binary
        tar -xzf $otelcolArchive -C $BinDir
    }
    Remove-Item $otelcolArchive -Force -ErrorAction SilentlyContinue
    Write-Success "otelcol-contrib installed to $otelcolPath"
} else {
    Write-Success "otelcol-contrib already installed"
}

# --- Install Prometheus ------------------------------------------------------

if (-not (Test-Path $prometheusPath)) {
    $promUrl = "https://github.com/prometheus/prometheus/releases/download/v${PrometheusVersion}/prometheus-${PrometheusVersion}.${OS}-${Arch}.zip"
    $promArchive = Join-Path $env:TEMP "prometheus.zip"

    Download-File -Url $promUrl -Destination $promArchive

    Write-Info "Extracting prometheus..."
    Expand-Archive -Path $promArchive -DestinationPath $env:TEMP -Force
    $promExtracted = Get-ChildItem "$env:TEMP\prometheus-*" -Directory | Select-Object -First 1
    if ($promExtracted) {
        Copy-Item (Join-Path $promExtracted.FullName "prometheus.exe") $BinDir -Force
    }
    Remove-Item $promArchive -Force -ErrorAction SilentlyContinue
    Remove-Item "$env:TEMP\prometheus-*" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Success "prometheus installed to $prometheusPath"
} else {
    Write-Success "prometheus already installed"
}

# --- Setup Config Files ------------------------------------------------------

$OtelConfig = Join-Path $ObsDir "otel-collector-config.yml"
$PromDir = Join-Path $ObsDir "prometheus"
$PromConfig = Join-Path $PromDir "prometheus.yml"

if (-not (Test-Path $OtelConfig)) {
        Write-Info "Creating default otel-collector-config.yml..."
        @"
###############################################################################
# OpenTelemetry Collector Configuration - Portable Bundle
#
# Receives OTLP signals from VS Code Copilot Chat and routes them:
#   - Metrics  -> Prometheus exporter (scraped by Prometheus)
#   - Traces   -> Debug console (for troubleshooting)
#   - Logs     -> Debug console (for troubleshooting)
###############################################################################

receivers:
    otlp:
        protocols:
            grpc:
                endpoint: 0.0.0.0:4317
            http:
                endpoint: 0.0.0.0:4318

processors:
    batch:
        send_batch_size: 512
        timeout: 5s

    resourcedetection:
        detectors: [env, system]
        system:
            hostname_sources: [os]
        timeout: 5s
        override: false

    attributes/copilot:
        actions:
            - key: deployment.environment
                value: local
                action: upsert
            - key: telemetry.source
                value: copilot-chat
                action: upsert

    memory_limiter:
        check_interval: 5s
        limit_mib: 512
        spike_limit_mib: 128

exporters:
    prometheus:
        endpoint: 0.0.0.0:8889
        namespace: copilot
        resource_to_telemetry_conversion:
            enabled: true

    debug:
        verbosity: basic
        sampling_initial: 5
        sampling_thereafter: 200

extensions:
    health_check:
        endpoint: 0.0.0.0:13133

service:
    extensions: [health_check]

    pipelines:
        traces:
            receivers: [otlp]
            processors: [memory_limiter, resourcedetection, attributes/copilot, batch]
            exporters: [debug]

        metrics:
            receivers: [otlp]
            processors: [memory_limiter, resourcedetection, attributes/copilot, batch]
            exporters: [prometheus, debug]

        logs:
            receivers: [otlp]
            processors: [memory_limiter, resourcedetection, attributes/copilot, batch]
            exporters: [debug]

    telemetry:
        logs:
            level: info
        metrics:
            readers:
                - pull:
                        exporter:
                            prometheus:
                                host: "0.0.0.0"
                                port: 8888
"@ | Set-Content -Path $OtelConfig -Encoding utf8
        Write-Success "Created otel-collector-config.yml"
}

New-Item -ItemType Directory -Force -Path $PromDir | Out-Null
if (-not (Test-Path $PromConfig)) {
        Write-Info "Creating default prometheus.yml..."
        @"
global:
    scrape_interval: 15s
    evaluation_interval: 15s

scrape_configs:
    - job_name: "otel-collector-copilot"
        static_configs:
            - targets: ["localhost:8889"]
                labels:
                    source: "copilot-chat"

    - job_name: "otel-collector-internal"
        static_configs:
            - targets: ["localhost:8888"]
"@ | Set-Content -Path $PromConfig -Encoding utf8
        Write-Success "Created prometheus.yml"
}

# --- Verification ------------------------------------------------------------

Write-Info "Verifying installation..."
if ((Test-Path $otelcolPath) -and (Test-Path $prometheusPath)) {
    Write-Success "All observability binaries installed successfully"
} else {
    Write-Err "Installation verification failed - binaries missing"
    exit 1
}

# --- Start and Health-Check --------------------------------------------------

Write-Info "Starting observability stack for verification..."

$PidDir = Join-Path $ObsDir ".pids"
$LogDir = Join-Path $ObsDir ".logs"
$PromDataDir = Join-Path $ObsDir ".prom-data"
$OtelConfig = Join-Path $ObsDir "otel-collector-config.yml"
$PromConfig = Join-Path (Join-Path $ObsDir "prometheus") "prometheus.yml"

# Start OTel Collector
$otelcolPidFile = Join-Path $PidDir "otelcol.pid"
$otelcolLog = Join-Path $LogDir "otelcol.log"

$otelcolRunning = $false
if (Test-Path $otelcolPidFile) {
    $existingPid = [int](Get-Content $otelcolPidFile -ErrorAction SilentlyContinue)
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Info "OTel Collector already running (PID $existingPid)"
        $otelcolRunning = $true
    }
}

if (-not $otelcolRunning) {
    if (Test-Path $OtelConfig) {
        Write-Info "Starting OTel Collector..."
        $otelProc = Start-Process -FilePath $otelcolPath `
            -ArgumentList "--config", $OtelConfig `
            -RedirectStandardOutput $otelcolLog `
            -RedirectStandardError (Join-Path $LogDir "otelcol-err.log") `
            -PassThru -WindowStyle Hidden
        Set-Content -Path $otelcolPidFile -Value $otelProc.Id
        Write-Info "OTel Collector started (PID $($otelProc.Id))"
    } else {
        Write-Warn "OTel Collector config not found at $OtelConfig - skipping start"
    }
}

# Start Prometheus
$promPidFile = Join-Path $PidDir "prometheus.pid"
$promLog = Join-Path $LogDir "prometheus.log"

$promRunning = $false
if (Test-Path $promPidFile) {
    $existingPid = [int](Get-Content $promPidFile -ErrorAction SilentlyContinue)
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Info "Prometheus already running (PID $existingPid)"
        $promRunning = $true
    }
}

if (-not $promRunning) {
    if (Test-Path $PromConfig) {
        Write-Info "Starting Prometheus..."
        $promProc = Start-Process -FilePath $prometheusPath `
            -ArgumentList "--config.file=$PromConfig", "--storage.tsdb.path=$PromDataDir", "--web.listen-address=:9090" `
            -RedirectStandardOutput $promLog `
            -RedirectStandardError (Join-Path $LogDir "prometheus-err.log") `
            -PassThru -WindowStyle Hidden
        Set-Content -Path $promPidFile -Value $promProc.Id
        Write-Info "Prometheus started (PID $($promProc.Id))"
    } else {
        Write-Warn "Prometheus config not found at $PromConfig - skipping start"
    }
}

# Wait for startup
Write-Info "Waiting for services to initialize (5s)..."
Start-Sleep -Seconds 5

# --- Endpoint Health Checks --------------------------------------------------

$healthOk = $true

# Check OTel Collector health endpoint (default: http://localhost:13133)
Write-Info "Checking OTel Collector health endpoint (http://localhost:13133)..."
try {
    $otelHealth = Invoke-WebRequest -Uri "http://localhost:13133" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($otelHealth.StatusCode -eq 200) {
        Write-Success "OTel Collector is healthy (HTTP 200)"
    } else {
        Write-Warn "OTel Collector responded with HTTP $($otelHealth.StatusCode)"
        $healthOk = $false
    }
} catch {
    Write-Warn "OTel Collector health check failed: $_"
    $healthOk = $false
}

# Check Prometheus health endpoint (default: http://localhost:9090/-/healthy)
Write-Info "Checking Prometheus health endpoint (http://localhost:9090/-/healthy)..."
try {
    $promHealth = Invoke-WebRequest -Uri "http://localhost:9090/-/healthy" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($promHealth.StatusCode -eq 200) {
        Write-Success "Prometheus is healthy (HTTP 200)"
    } else {
        Write-Warn "Prometheus responded with HTTP $($promHealth.StatusCode)"
        $healthOk = $false
    }
} catch {
    Write-Warn "Prometheus health check failed: $_"
    $healthOk = $false
}

# Check Prometheus query API
Write-Info "Checking Prometheus query API (http://localhost:9090/api/v1/status/config)..."
try {
    $promApi = Invoke-WebRequest -Uri "http://localhost:9090/api/v1/status/config" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($promApi.StatusCode -eq 200) {
        Write-Success "Prometheus API is accessible"
    } else {
        Write-Warn "Prometheus API responded with HTTP $($promApi.StatusCode)"
    }
} catch {
    Write-Warn "Prometheus API check failed (non-critical): $_"
}

# --- Summary -----------------------------------------------------------------

Write-Host ""
if ($healthOk) {
    Write-Success "Observability stack is running and all endpoints are accessible"
    Write-Info "  OTel Collector: http://localhost:13133 (health) / http://localhost:4318 (OTLP)"
    Write-Info "  Prometheus:     http://localhost:9090 (UI + API)"
    exit 0
} else {
    Write-Warn "Observability stack started but some health checks failed"
    Write-Info "Check logs at: $LogDir"
    Write-Info "  OTel Collector log: $otelcolLog"
    Write-Info "  Prometheus log:     $promLog"
    exit 1
}
