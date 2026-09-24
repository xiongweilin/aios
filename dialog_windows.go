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
	appDir, err := stateDir()
	if err != nil {
		return err
	}
	logDir := filepath.Join(appDir, "logs")
	if err := os.MkdirAll(logDir, 0700); err != nil {
		return err
	}
	log, err := os.OpenFile(filepath.Join(logDir, "selector-host.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer log.Close()
	ps := filepath.Join(os.Getenv("WINDIR"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	cmd := exec.Command(ps, "-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", path, "-ExePath", exe)
	const createNoWindow = 0x08000000
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
	cmd.Stdout = log
	cmd.Stderr = log
	return cmd.Run()
}
