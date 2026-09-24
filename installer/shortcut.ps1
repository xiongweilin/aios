param(
  [Parameter(Mandatory)][string]$InstallDir,
  [Parameter(Mandatory)][string]$ManagerPath
)

$ErrorActionPreference = 'Stop'
$startMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Metratio'
$startMenuShortcut = Join-Path $startMenuDir 'AIOS.lnk'
$desktopShortcut = Join-Path $env:USERPROFILE 'Desktop\AIOS.lnk'

New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($shortcutPath in @($startMenuShortcut, $desktopShortcut)) {
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $ManagerPath
  $shortcut.WorkingDirectory = $InstallDir
  $shortcut.Description = 'AIOS Manager'
  $shortcut.Save()
}

$uninstallPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MetratioAIOS'
New-Item -Path $uninstallPath -Force | Out-Null
New-ItemProperty -Path $uninstallPath -Name DisplayName -Value 'AIOS Manager' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallPath -Name InstallLocation -Value $InstallDir -PropertyType String -Force | Out-Null
New-ItemProperty -Path $uninstallPath -Name UninstallString -Value ('"{0}" uninstall' -f $ManagerPath) -PropertyType String -Force | Out-Null
