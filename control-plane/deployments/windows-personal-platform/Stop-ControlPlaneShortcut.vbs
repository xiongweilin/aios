Option Explicit

' Hidden, elevated entry point for the Start Menu shortcut.
Dim shell, app, fso, scriptDir, ps1, pwsh, arguments
Set shell = CreateObject("WScript.Shell")
Set app = CreateObject("Shell.Application")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(scriptDir, "Stop-ControlPlane.ps1")
pwsh = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\scoop\apps\pwsh\current\pwsh.exe"
If Not fso.FileExists(pwsh) Then pwsh = "pwsh.exe"

arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File " & Chr(34) & ps1 & Chr(34)
app.ShellExecute pwsh, arguments, scriptDir, "runas", 0
WScript.Quit 0
