$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dist = Join-Path $root 'dist'
$manager = Join-Path $dist 'aios.exe'
$developerController = Join-Path $dist 'aios-dev.exe'
$setup = Join-Path $dist 'AIOS-Setup.exe'
$payload = Join-Path $root 'installer\payload'
New-Item -ItemType Directory -Path $dist,$payload -Force | Out-Null
$previousGOOS = $env:GOOS
$previousGOARCH = $env:GOARCH
Push-Location $root
try {
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    go build -trimpath -ldflags '-s -w -H windowsgui' -o $developerController .
    if ($LASTEXITCODE -ne 0) { throw "developer controller build failed with exit code $LASTEXITCODE" }

    go build -trimpath -tags product -ldflags '-s -w -H windowsgui' -o $manager .
    if ($LASTEXITCODE -ne 0) { throw "AIOS Manager build failed with exit code $LASTEXITCODE" }

    Copy-Item -LiteralPath $manager -Destination (Join-Path $payload 'aios.exe') -Force
    $stableProfile = Join-Path $root 'profiles\stable.json'
    if (Test-Path -LiteralPath $stableProfile) {
        go run .\cmd\verify-profile $stableProfile
        if ($LASTEXITCODE -ne 0) { throw "stable profile validation failed with exit code $LASTEXITCODE" }
        Copy-Item -LiteralPath $stableProfile -Destination (Join-Path $payload 'stable-profile.json') -Force
    }
    go build -trimpath -ldflags '-s -w -H windowsgui' -o $setup .\installer
    if ($LASTEXITCODE -ne 0) { throw "AIOS Setup build failed with exit code $LASTEXITCODE" }
}
finally {
    Remove-Item -LiteralPath (Join-Path $payload 'aios.exe') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $payload 'stable-profile.json') -Force -ErrorAction SilentlyContinue
    if ($null -eq $previousGOOS) { Remove-Item Env:GOOS -ErrorAction SilentlyContinue } else { $env:GOOS = $previousGOOS }
    if ($null -eq $previousGOARCH) { Remove-Item Env:GOARCH -ErrorAction SilentlyContinue } else { $env:GOARCH = $previousGOARCH }
    Pop-Location
}
Write-Host "Built $manager (public Manager), $setup (single user-facing installer), and $developerController (developer-only)."
