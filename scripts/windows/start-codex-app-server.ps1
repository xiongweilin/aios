#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 18786,
    [string]$WorkspaceRoot = '',
    [string]$AutodevStateRoot = '',
    [string]$ControlPlaneStateRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$bridgeRoot = Join-Path $repositoryRoot '.aios-data\codex-bridge'
$tokenPath = Join-Path $bridgeRoot 'ws-token'
$pidPath = Join-Path $bridgeRoot 'app-server.pid'
$stdoutPath = Join-Path $bridgeRoot 'app-server.stdout.log'
$stderrPath = Join-Path $bridgeRoot 'app-server.stderr.log'

function Resolve-Root([string]$Value, [string]$Default) {
    $selected = if ([string]::IsNullOrWhiteSpace($Value)) { $Default } else { $Value }
    if ([IO.Path]::IsPathRooted($selected)) {
        return [IO.Path]::GetFullPath($selected)
    }
    return [IO.Path]::GetFullPath((Join-Path $repositoryRoot $selected))
}

function Write-JsonAtomic([string]$Path, [object]$Value) {
    if (Test-Path -LiteralPath $Path -PathType Container) {
        throw "Expected a file path, but found a directory: $Path"
    }
    $temporary = "$Path.$PID.tmp"
    $json = ConvertTo-Json -InputObject $Value -Depth 8
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Test-Ready {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/readyz" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

New-Item -ItemType Directory -Path $bridgeRoot -Force | Out-Null
$workspaceHostRoot = Resolve-Root $WorkspaceRoot '.'
$autodevHostRoot = Resolve-Root $AutodevStateRoot '.aios-data\autonomous-development'
$controlPlaneHostRoot = Resolve-Root $ControlPlaneStateRoot '.aios-data\control-plane'

Write-JsonAtomic (Join-Path $bridgeRoot 'autodev-path-map.json') @{
    version = 1
    roots = @(
        @{ containerRoot = '/workspace'; hostRoot = $workspaceHostRoot }
        @{ containerRoot = '/data/autonomous-development'; hostRoot = $autodevHostRoot }
    )
}
Write-JsonAtomic (Join-Path $bridgeRoot 'control-plane-path-map.json') @{
    version = 1
    roots = @(
        @{ containerRoot = '/data/control-plane'; hostRoot = $controlPlaneHostRoot }
    )
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $ownerIds = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    $recordedPid = 0
    if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
        [void][int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$recordedPid)
    }
    if ($ownerIds.Count -eq 1 -and $ownerIds[0] -eq $recordedPid -and (Test-Ready)) {
        Write-Output "Codex App Server already ready on loopback port $Port (pid=$recordedPid)."
        exit 0
    }
    throw "Port $Port is already owned by an unverified process; no process was changed."
}

if (Test-Path -LiteralPath $tokenPath -PathType Container) {
    throw "Expected a token file, but found a directory: $tokenPath"
}
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = [byte[]]::new(32)
    try {
        $random.GetBytes($bytes)
        $token = [Convert]::ToBase64String($bytes)
        $temporary = "$tokenPath.$PID.tmp"
        [IO.File]::WriteAllText($temporary, $token, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $tokenPath
    } finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $random.Dispose()
    }
}

$codex = Get-Command codex.cmd -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $codex) {
    $codex = Get-Command codex -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
}
if ($null -eq $codex) {
    throw 'Codex CLI executable was not found on PATH.'
}

$startParameters = @{
    FilePath = $codex.Source
    ArgumentList = @(
        'app-server',
        '--listen', "ws://127.0.0.1:$Port",
        '--ws-auth', 'capability-token',
        '--ws-token-file', $tokenPath
    )
    WorkingDirectory = $repositoryRoot
    RedirectStandardOutput = $stdoutPath
    RedirectStandardError = $stderrPath
    WindowStyle = 'Hidden'
    PassThru = $true
}
$process = Start-Process @startParameters
$deadline = [DateTime]::UtcNow.AddSeconds(20)
$ownerId = 0
while ([DateTime]::UtcNow -lt $deadline) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $owners = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
        if ($owners.Count -ne 1) {
            throw "Codex App Server port $Port has multiple listeners."
        }
        $ownerId = $owners[0]
        if (Test-Ready) {
            [IO.File]::WriteAllText($pidPath, [string]$ownerId, [Text.UTF8Encoding]::new($false))
            Write-Output "Codex App Server ready on loopback port $Port (pid=$ownerId)."
            Write-Output 'Docker clients use host.docker.internal; the transport token remains in ignored local state.'
            exit 0
        }
    }
    if ($process.HasExited) {
        throw "Codex App Server exited during startup (exit=$($process.ExitCode)); inspect its local logs."
    }
    Start-Sleep -Milliseconds 250
    $process.Refresh()
}

if ($ownerId -gt 0) {
    $owner = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
    if ($null -ne $owner -and $owner.Path -match '(?i)codex') {
        Stop-Process -Id $ownerId -Force
    }
} elseif (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
throw 'Codex App Server did not become ready within 20 seconds.'
