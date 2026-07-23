#!/usr/bin/env pwsh
# status.ps1 - Check observability stack status on Windows.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ObsDir = Join-Path (Split-Path -Parent $ScriptDir) "observability"
$PidDir = Join-Path $ObsDir ".pids"

function Test-ServicePid {
    param([string]$Name)
    $pidFile = Join-Path $PidDir "$Name.pid"

    if (-not (Test-Path $pidFile)) {
        Write-Host "  [--] $Name not running"
        return
    }

    try {
        $pidValue = [int](Get-Content $pidFile -Raw).Trim()
    }
    catch {
        Write-Host "  [!!] $Name has invalid pid file"
        return
    }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        Write-Host "  [ok] $Name running (PID $pidValue)"
    }
    else {
        Write-Host "  [!!] $Name stale pid ($pidValue)"
    }
}

function Test-Http {
    param([string]$Name, [string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) {
            Write-Host "  [ok] $Name healthy"
            return
        }
        Write-Host "  [!!] $Name HTTP $($resp.StatusCode)"
    }
    catch {
        Write-Host "  [--] $Name unreachable"
    }
}

Write-Host "========================================"
Write-Host " Observability Status (Windows)"
Write-Host "========================================"
Write-Host ""
Write-Host "Process status:"
Test-ServicePid -Name "otelcol"
Test-ServicePid -Name "prometheus"
Write-Host ""
Write-Host "Health status:"
Test-Http -Name "OTel Collector" -Url "http://localhost:13133"
Test-Http -Name "Prometheus" -Url "http://localhost:9090/-/ready"
