package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func showSelector(script string) error {
	file, err := os.CreateTemp(os.TempDir(), "aios-selector-*.ps1")
	if err != nil {
		return err
	}
	path := file.Name()
	defer os.Remove(path)
	if _, err := file.WriteString(script); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	ps := filepath.Join(os.Getenv("WINDIR"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	cmd := exec.Command(ps, "-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", path, "-ExePath", exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}
