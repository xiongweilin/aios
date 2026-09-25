#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18786
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pidPath = Join-Path $repositoryRoot '.aios-data\codex-bridge\app-server.pid'
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    Write-Output 'No recorded Codex App Server process.'
    exit 0
}

$recordedPid = 0
if (-not [int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$recordedPid)) {
    throw 'Codex App Server PID record is malformed.'
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
$ownerIds = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
if ($ownerIds.Count -eq 0) {
    Remove-Item -LiteralPath $pidPath -Force
    Write-Output 'Codex App Server is already stopped.'
    exit 0
}
if ($ownerIds.Count -ne 1 -or $ownerIds[0] -ne $recordedPid) {
    throw "Port $Port is no longer owned by the recorded Codex App Server; no process was stopped."
}
$process = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
if ($null -eq $process -or $process.Path -notmatch '(?i)codex') {
    throw 'Recorded listener is not the Codex CLI process; no process was stopped.'
}
Stop-Process -Id $recordedPid -Force
$deadline = [DateTime]::UtcNow.AddSeconds(10)
while ([DateTime]::UtcNow -lt $deadline) {
    if (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $pidPath -Force
        Write-Output 'Codex App Server stopped.'
        exit 0
    }
    Start-Sleep -Milliseconds 250
}
throw 'Codex App Server listener did not stop within 10 seconds.'
