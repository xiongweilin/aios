#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$secretRoot = Join-Path $repositoryRoot '.aios-data\secrets'
$secretPath = Join-Path $secretRoot 'operator-hmac'

New-Item -ItemType Directory -Path $secretRoot -Force | Out-Null
if (Test-Path -LiteralPath $secretPath -PathType Container) {
    throw "Expected an Operator HMAC secret file, but found a directory: $secretPath"
}
if (Test-Path -LiteralPath $secretPath -PathType Leaf) {
    if ((Get-Item -LiteralPath $secretPath).Length -lt 32) {
        throw "Existing Operator HMAC secret file is shorter than 32 bytes: $secretPath"
    }
    Write-Output "Operator HMAC secret is ready at $secretPath."
    exit 0
}

$random = [Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = [byte[]]::new(32)
$temporary = "$secretPath.$PID.tmp"
try {
    $random.GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes)
    [IO.File]::WriteAllText($temporary, $secret, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $secretPath
} finally {
    [Array]::Clear($bytes, 0, $bytes.Length)
    $random.Dispose()
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporary
    }
}
Write-Output "Operator HMAC secret is ready at $secretPath."
