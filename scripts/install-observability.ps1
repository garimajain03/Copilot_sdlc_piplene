#Requires -Version 5.1
###############################################################################
# install-observability.ps1 — Download OTel Collector & Prometheus binaries (Windows)
#
# Downloads official release binaries to observability/.bin/ — no admin required.
#
# Usage:
#   .\scripts\install-observability.ps1            # Install both
#   .\scripts\install-observability.ps1 -Check     # Check if installed
#   .\scripts\install-observability.ps1 -Json      # Output status as JSON
#
# Supports: Windows (amd64)
###############################################################################

[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

# ─── Configuration ────────────────────────────────────────────────────────────

$OtelcolVersion = if ($env:OTELCOL_VERSION) { $env:OTELCOL_VERSION } else { "0.151.0" }
$PrometheusVersion = if ($env:PROMETHEUS_VERSION) { $env:PROMETHEUS_VERSION } else { "3.4.1" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$BinDir = Join-Path $RepoRoot "observability" ".bin"
$ObsDir = Join-Path $RepoRoot "observability"

# ─── Helpers ──────────────────────────────────────────────────────────────────

function Write-Info { param($Message) Write-Host "i  $Message" -ForegroundColor Blue }
function Write-Success { param($Message) Write-Host "v  $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "!  $Message" -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host "x  $Message" -ForegroundColor Red }

# ─── Platform Detection ──────────────────────────────────────────────────────

$Arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "386" }
$OS = "windows"

# ─── Download Helper ─────────────────────────────────────────────────────────

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )
    Write-Info "Downloading: $Url"
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -MaximumRetryCount 3
    } catch {
        Write-Err "Download failed: $_"
        throw
    }
}

# ─── Check Mode ──────────────────────────────────────────────────────────────

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

# ─── Install ─────────────────────────────────────────────────────────────────

Write-Info "Installing observability binaries for Windows ($Arch)..."

# Create directories
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".pids") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".prom-data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ObsDir ".hook-state") | Out-Null

# ─── Install OTel Collector ──────────────────────────────────────────────────

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

# ─── Install Prometheus ──────────────────────────────────────────────────────

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

# ─── Verification ────────────────────────────────────────────────────────────

Write-Info "Verifying installation..."
if ((Test-Path $otelcolPath) -and (Test-Path $prometheusPath)) {
    Write-Success "All observability binaries installed successfully"
    exit 0
} else {
    Write-Err "Installation verification failed"
    exit 1
}
