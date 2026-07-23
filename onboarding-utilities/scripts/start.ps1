#!/usr/bin/env pwsh
# start.ps1 - Start observability stack on Windows.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ObsDir = Join-Path (Split-Path -Parent $ScriptDir) "observability"
$PidDir = Join-Path $ObsDir ".pids"
$LogDir = Join-Path $ObsDir ".logs"
$PromDataDir = Join-Path $ObsDir ".prom-data"
$BinDir = Join-Path $ObsDir ".bin"

$otelExe = Join-Path $BinDir "otelcol-contrib.exe"
$promExe = Join-Path $BinDir "prometheus.exe"
$otelConfig = Join-Path $ObsDir "otel-collector-config.yml"
$promConfig = Join-Path (Join-Path $ObsDir "prometheus") "prometheus.yml"

New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $PromDataDir -Force | Out-Null

function Get-AliveProcess {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) { return $null }

    try {
        $pidValue = [int](Get-Content $PidFile -Raw).Trim()
    }
    catch {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        return $null
    }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        return $null
    }
    return $proc
}

function Start-ServiceProc {
    param(
        [string]$Name,
        [string]$ExePath,
        [string[]]$Args,
        [string]$PidFile,
        [string]$StdOut,
        [string]$StdErr
    )

    $existing = Get-AliveProcess -PidFile $PidFile
    if ($null -ne $existing) {
        Write-Host "  [ok] $Name already running (PID $($existing.Id))"
        return
    }

    if (-not (Test-Path $ExePath)) {
        throw "$Name binary not found: $ExePath"
    }

    $proc = Start-Process -FilePath $ExePath `
        -ArgumentList $Args `
        -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr `
        -PassThru

    Set-Content -Path $PidFile -Value $proc.Id -NoNewline
    Write-Host "  [ok] $Name started (PID $($proc.Id))"
}

Write-Host "========================================"
Write-Host " Observability Stack (Windows)"
Write-Host "========================================"

if (-not (Test-Path $otelConfig)) { throw "OTel config missing: $otelConfig" }
if (-not (Test-Path $promConfig)) { throw "Prometheus config missing: $promConfig" }

Start-ServiceProc -Name "otelcol" -ExePath $otelExe -Args @("--config=$otelConfig") `
    -PidFile (Join-Path $PidDir "otelcol.pid") `
    -StdOut (Join-Path $LogDir "otelcol.log") `
    -StdErr (Join-Path $LogDir "otelcol-err.log")

Start-ServiceProc -Name "prometheus" -ExePath $promExe -Args @(
    "--config.file=$promConfig",
    "--storage.tsdb.path=$PromDataDir",
    "--web.listen-address=:9090",
    "--storage.tsdb.retention.time=7d"
) -PidFile (Join-Path $PidDir "prometheus.pid") `
  -StdOut (Join-Path $LogDir "prometheus.log") `
  -StdErr (Join-Path $LogDir "prometheus-err.log")

Write-Host ""
Write-Host "Prometheus: http://localhost:9090"
Write-Host "OTel health: http://localhost:13133"
