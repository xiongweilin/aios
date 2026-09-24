$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$output = Join-Path $root 'dist\aios.exe'
New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
Push-Location $root
try {
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    go build -trimpath -ldflags '-s -w -H windowsgui' -o $output .
    if ($LASTEXITCODE -ne 0) { throw "go build failed with exit code $LASTEXITCODE" }
}
finally {
    Remove-Item Env:GOOS -ErrorAction SilentlyContinue
    Remove-Item Env:GOARCH -ErrorAction SilentlyContinue
    Pop-Location
}
Write-Host "Built $output"
