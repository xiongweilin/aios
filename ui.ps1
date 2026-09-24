param([Parameter(Mandatory)][string]$ExePath)

$ErrorActionPreference = 'Stop'
Write-Output 'AIOS selector: host started'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Write-Output 'AIOS selector: UI assemblies loaded'

function Invoke-Aios([string[]]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $escaped = foreach ($arg in $Arguments) { '"' + $arg.Replace('"', '\"') + '"' }
    $psi.Arguments = $escaped -join ' '
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    [pscustomobject]@{ ExitCode = $process.ExitCode; Text = ($stdout + $stderr).Trim() }
}

$services = @(
    [pscustomobject]@{ Id = 'world-runtime'; Label = 'World Runtime'; Layer = 'dependency' },
    [pscustomobject]@{ Id = 'personal-world'; Label = 'Personal World'; Layer = 'dependency' },
    [pscustomobject]@{ Id = 'litellm-gateway'; Label = 'LiteLLM Gateway'; Layer = 'dependency' },
    [pscustomobject]@{ Id = 'control-plane'; Label = 'Control Plane'; Layer = 'domain' },
    [pscustomobject]@{ Id = 'administrative-orchestrator'; Label = 'Administrative Orchestrator'; Layer = 'domain' },
    [pscustomobject]@{ Id = 'autonomous-development'; Label = 'Autonomous Development'; Layer = 'domain' }
)
$profileResult = Invoke-Aios @('profile', 'get')
Write-Output "AIOS selector: profile command exit $($profileResult.ExitCode)"
$remembered = @{}
if ($profileResult.ExitCode -eq 0) {
    foreach ($id in ($profileResult.Text -split "`r?`n")) { if ($id) { $remembered[$id] = $true } }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'AIOS 服务控制'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(520, 635)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.ShowInTaskbar = $true
$form.TopMost = $true
$form.Add_Shown({
    $form.Activate()
    $form.BringToFront()
})

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Personal AIOS'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 15, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(18, 12)
$title.Size = New-Object System.Drawing.Size(300, 30)
$form.Controls.Add($title)

$defaultNote = New-Object System.Windows.Forms.Label
$defaultNote.Text = '默认入口：Agency Console BFF（随启动/关闭自动处理，无需选择）'
$defaultNote.Location = New-Object System.Drawing.Point(20, 48)
$defaultNote.Size = New-Object System.Drawing.Size(480, 24)
$form.Controls.Add($defaultNote)

$boxes = @{}
function Add-ServiceLayer([string]$Name, [string]$Layer, [int]$Top) {
    $group = New-Object System.Windows.Forms.GroupBox
    $group.Text = $Name
    $group.Location = New-Object System.Drawing.Point(18, $Top)
    $group.Size = New-Object System.Drawing.Size(484, 145)
    $form.Controls.Add($group)
    $subset = @($services | Where-Object Layer -eq $Layer)
    for ($i = 0; $i -lt $subset.Count; $i++) {
        $check = New-Object System.Windows.Forms.CheckBox
        $check.Text = $subset[$i].Label
        $check.Tag = $subset[$i].Id
        $check.Location = New-Object System.Drawing.Point(18, (27 + $i * 34))
        $check.Size = New-Object System.Drawing.Size(440, 27)
        $check.Checked = $remembered.ContainsKey($subset[$i].Id)
        $group.Controls.Add($check)
        $boxes[$subset[$i].Id] = $check
    }
}
Add-ServiceLayer '依赖层' 'dependency' 78
Add-ServiceLayer 'Domain 层' 'domain' 232

$hint = New-Object System.Windows.Forms.Label
$hint.Text = 'Control Plane 会自动启动其硬依赖 World Runtime；profile 即时保存。打开窗口本身不改变服务状态。'
$hint.Location = New-Object System.Drawing.Point(20, 390)
$hint.Size = New-Object System.Drawing.Size(480, 36)
$form.Controls.Add($hint)

$output = New-Object System.Windows.Forms.TextBox
$output.Location = New-Object System.Drawing.Point(20, 430)
$output.Size = New-Object System.Drawing.Size(480, 112)
$output.Multiline = $true
$output.ReadOnly = $true
$output.ScrollBars = 'Vertical'
$output.Font = New-Object System.Drawing.Font('Consolas', 9)
$form.Controls.Add($output)

function Get-SelectedIds {
    @($services | Where-Object { $boxes[$_.Id].Checked } | ForEach-Object Id)
}
function Save-Profile {
    $ids = Get-SelectedIds
    $result = Invoke-Aios (@('profile', 'save') + $ids)
    if ($result.ExitCode -ne 0) { $output.Text = $result.Text }
}
function Get-ActionArgs([string]$Verb) {
    $ids = Get-SelectedIds
    if ($ids.Count -eq 0) { return @($Verb, '--default-only') }
    return @($Verb) + $ids
}
function Invoke-Action([string]$Verb) {
    Save-Profile
    $startButton.Enabled = $false
    $stopButton.Enabled = $false
    $statusButton.Enabled = $false
    $output.Text = "正在执行 $Verb ..."
    [System.Windows.Forms.Application]::DoEvents()
    try {
        $result = Invoke-Aios (Get-ActionArgs $Verb)
        $output.Text = if ($result.Text) { $result.Text } else { "操作完成（exit $($result.ExitCode)）。" }
        if ($result.ExitCode -ne 0) { $output.Text += "`r`n执行失败，请查看上方结果及本机日志。" }
    }
    finally {
        $startButton.Enabled = $true
        $stopButton.Enabled = $true
        $statusButton.Enabled = $true
    }
}

foreach ($check in $boxes.Values) { $check.add_CheckedChanged({ Save-Profile }) }

$startButton = New-Object System.Windows.Forms.Button
$startButton.Text = '启动所选'
$startButton.Location = New-Object System.Drawing.Point(20, 555)
$startButton.Size = New-Object System.Drawing.Size(120, 38)
$startButton.Add_Click({ Invoke-Action 'start' })
$form.Controls.Add($startButton)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = '关闭所选'
$stopButton.Location = New-Object System.Drawing.Point(150, 555)
$stopButton.Size = New-Object System.Drawing.Size(120, 38)
$stopButton.Add_Click({ Invoke-Action 'stop' })
$form.Controls.Add($stopButton)

$statusButton = New-Object System.Windows.Forms.Button
$statusButton.Text = '状态'
$statusButton.Location = New-Object System.Drawing.Point(280, 555)
$statusButton.Size = New-Object System.Drawing.Size(90, 38)
$statusButton.Add_Click({
    $ids = Get-SelectedIds
    $args = @('status') + $ids
    if ($ids.Count -eq 0) { $args = @('status') }
    $result = Invoke-Aios $args
    $output.Text = $result.Text
})
$form.Controls.Add($statusButton)

$logsButton = New-Object System.Windows.Forms.Button
$logsButton.Text = '日志'
$logsButton.Location = New-Object System.Drawing.Point(380, 555)
$logsButton.Size = New-Object System.Drawing.Size(120, 38)
$logsButton.Add_Click({
    $ids = Get-SelectedIds
    $args = @('logs') + $ids
    if ($ids.Count -eq 0) { $args = @('logs') }
    $result = Invoke-Aios $args
    $output.Text = $result.Text
})
$form.Controls.Add($logsButton)

Write-Output 'AIOS selector: entering dialog'
[void]$form.ShowDialog()
Write-Output 'AIOS selector: dialog closed'
