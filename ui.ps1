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
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    [pscustomobject]@{ ExitCode = $process.ExitCode; Text = ($stdout + $stderr).Trim() }
}

function Start-AiosAsync([string[]]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.WorkingDirectory = Split-Path -Parent $ExePath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $escaped = foreach ($arg in $Arguments) { '"' + $arg.Replace('"', '\"') + '"' }
    $psi.Arguments = $escaped -join ' '
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $process
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
$defaultNote.Text = '默认入口：Agency Console Web + BFF（随启动/关闭自动处理，无需选择）'
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
function Set-ActionControls([bool]$Enabled) {
    $startButton.Enabled = $Enabled
    $stopButton.Enabled = $Enabled
    $statusButton.Enabled = $Enabled
    $logsButton.Enabled = $Enabled
    foreach ($check in $boxes.Values) { $check.Enabled = $Enabled }
}
function Invoke-Action([string]$Verb) {
    Save-Profile
    try {
        Set-ActionControls $false
        $script:pendingVerb = $Verb
        $script:actionStartedAt = [DateTime]::UtcNow
        $script:pendingAction = Start-AiosAsync (Get-ActionArgs $Verb)
        $output.Text = "正在执行 $Verb ... 窗口保持可响应。"
        $actionTimer.Start()
    } catch {
        $output.Text = "无法启动 $Verb：$($_.Exception.Message)"
        Set-ActionControls $true
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

$script:pendingAction = $null
$script:pendingVerb = ''
$script:actionStartedAt = [DateTime]::UtcNow
$actionTimer = New-Object System.Windows.Forms.Timer
$actionTimer.Interval = 500
$actionTimer.Add_Tick({
    $action = $script:pendingAction
    if ($null -eq $action) { return }
    if (-not $action.HasExited) {
        $elapsed = [int]([DateTime]::UtcNow - $script:actionStartedAt).TotalSeconds
        $output.Text = "正在执行 $($script:pendingVerb)（已 $elapsed 秒）；窗口保持可响应。"
        return
    }
    $actionTimer.Stop()
    $exitCode = $action.ExitCode
    $output.Text = if ($exitCode -eq 0) { "操作完成（exit $exitCode）。可用状态按钮确认服务状态。" } else { "操作失败（exit $exitCode）。请用日志按钮查看本机日志。" }
    $action.Dispose()
    $script:pendingAction = $null
    Set-ActionControls $true
})

Write-Output 'AIOS selector: entering dialog'
[void]$form.ShowDialog()
Write-Output 'AIOS selector: dialog closed'
