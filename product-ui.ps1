param([Parameter(Mandatory)][string]$ManagerPath)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$home = Join-Path $env:USERPROFILE '.aios'
$profilePath = Join-Path $home 'config\release-profile.json'
$hasProfile = Test-Path -LiteralPath $profilePath

$form = New-Object System.Windows.Forms.Form
$form.Text = 'AIOS Manager'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(620, 390)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true

$title = New-Object System.Windows.Forms.Label
$title.Text = 'AIOS'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 22, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(28, 22)
$title.Size = New-Object System.Drawing.Size(300, 42)
$form.Controls.Add($title)

$tagline = New-Object System.Windows.Forms.Label
$tagline.Text = '安装与生命周期由已验证的兼容 profile 驱动'
$tagline.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$tagline.ForeColor = [System.Drawing.Color]::FromArgb(92, 105, 130)
$tagline.Location = New-Object System.Drawing.Point(31, 67)
$tagline.Size = New-Object System.Drawing.Size(480, 25)
$form.Controls.Add($tagline)

$status = New-Object System.Windows.Forms.Label
$status.Text = if ($hasProfile) { '发现 profile 文件；请先用状态检查确认其来源与兼容性。' } else { '兼容组件 Release 尚未发布；未安装任何组件。' }
$status.Font = New-Object System.Drawing.Font('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
$status.ForeColor = if ($hasProfile) { [System.Drawing.Color]::FromArgb(49, 105, 82) } else { [System.Drawing.Color]::FromArgb(73, 91, 148) }
$status.Location = New-Object System.Drawing.Point(31, 123)
$status.Size = New-Object System.Drawing.Size(555, 42)
$form.Controls.Add($status)

$detail = New-Object System.Windows.Forms.Label
$detail.Text = "长期状态、配置、数据、日志、组件与领域目录位于：`r`n$home`r`n没有兼容 profile 时不会猜测版本或下载 latest。"
$detail.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$detail.ForeColor = [System.Drawing.Color]::FromArgb(82, 96, 120)
$detail.Location = New-Object System.Drawing.Point(31, 173)
$detail.Size = New-Object System.Drawing.Size(555, 70)
$form.Controls.Add($detail)

function Add-Button([string]$Text, [int]$Left, [scriptblock]$Action, [bool]$Enabled = $true) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Location = New-Object System.Drawing.Point($Left, 280)
    $button.Size = New-Object System.Drawing.Size(132, 42)
    $button.Enabled = $Enabled
    $button.Add_Click($Action)
    $form.Controls.Add($button)
}

Add-Button '查看发布状态' 28 { Start-Process 'https://github.com/xiongweilin/aios/releases' }
Add-Button '打开 AIOS 网页' 170 { Start-Process 'https://aios.metratio.com' }
Add-Button '打开日志目录' 312 { & $ManagerPath logs }
Add-Button '卸载 Manager' 454 { & $ManagerPath uninstall }

$footer = New-Object System.Windows.Forms.Label
$footer.Text = '程序可更新或重装；卸载 Manager 不会删除 ~/.aios 中的长期状态。'
$footer.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$footer.ForeColor = [System.Drawing.Color]::FromArgb(125, 137, 157)
$footer.Location = New-Object System.Drawing.Point(31, 345)
$footer.Size = New-Object System.Drawing.Size(555, 23)
$form.Controls.Add($footer)

[void]$form.ShowDialog()
