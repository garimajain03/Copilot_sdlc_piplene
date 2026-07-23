#!/usr/bin/env pwsh
# stop.ps1 - Stop observability stack on Windows.

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ObsDir = Join-Path (Split-Path -Parent $ScriptDir) "observability"
$PidDir = Join-Path $ObsDir ".pids"

function Stop-ServicePid {
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
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Write-Host "  [!!] $Name invalid pid file removed"
        return
    }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Write-Host "  [--] $Name stale pid removed"
        return
    }

    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Host "  [ok] $Name stopped (PID $pidValue)"
}

Write-Host "Stopping observability stack..."
Stop-ServicePid -Name "otelcol"
Stop-ServicePid -Name "prometheus"
Write-Host "Done."
