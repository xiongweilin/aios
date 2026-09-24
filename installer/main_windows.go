//go:build windows

package main

import (
	"bytes"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"

	"github.com/xiongweilin/aios/internal/profile"
)

//go:embed payload/* shortcut.ps1
var bundle embed.FS

func main() {
	if err := install(); err != nil {
		messageBox("AIOS Setup", err.Error(), 0x10)
		os.Exit(1)
	}
}

func install() error {
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return fmt.Errorf("LOCALAPPDATA is not set; Setup cannot choose an installation directory")
	}
	userHome := os.Getenv("USERPROFILE")
	if userHome == "" {
		return fmt.Errorf("USERPROFILE is not set; Setup cannot create the AIOS state directory")
	}
	managerBinary, err := bundle.ReadFile("payload/aios.exe")
	if err != nil {
		return fmt.Errorf("Setup bundle has no AIOS Manager payload; rebuild with build.ps1")
	}
	profileBytes, profileErr := bundle.ReadFile("payload/stable-profile.json")
	if profileErr != nil && !errors.Is(profileErr, fs.ErrNotExist) {
		return profileErr
	}
	if profileErr == nil {
		if _, err := profile.ParseReleaseProfile(profileBytes); err != nil {
			return fmt.Errorf("Setup contains an invalid compatibility profile: %w", err)
		}
	}
	installDir := filepath.Join(localAppData, "Programs", "Metratio", "AIOS")
	managerPath := filepath.Join(installDir, "aios.exe")
	stateRoot := filepath.Join(userHome, ".aios")
	for _, path := range []string{
		installDir,
		filepath.Join(stateRoot, "config"),
		filepath.Join(stateRoot, "state"),
		filepath.Join(stateRoot, "data"),
		filepath.Join(stateRoot, "logs"),
		filepath.Join(stateRoot, "components"),
		filepath.Join(stateRoot, "domains", "autonomous-development"),
		filepath.Join(stateRoot, "domains", "administrative"),
	} {
		if err := os.MkdirAll(path, 0700); err != nil {
			return fmt.Errorf("create %s: %w", path, err)
		}
	}
	if existing, err := os.ReadFile(managerPath); err == nil {
		if !bytes.Equal(existing, managerBinary) {
			return fmt.Errorf("a different AIOS Manager is already installed at %s; Setup will not overwrite a running or installed program", managerPath)
		}
	} else if !os.IsNotExist(err) {
		return err
	} else if err := atomicInstall(managerPath, managerBinary); err != nil {
		return err
	}
	if profileErr == nil {
		profilePath := filepath.Join(stateRoot, "config", "release-profile.json")
		if err := atomicInstall(profilePath, profileBytes); err != nil {
			return fmt.Errorf("install compatible profile: %w", err)
		}
	}
	if err := createShortcuts(installDir, managerPath); err != nil {
		return fmt.Errorf("Manager was installed, but shortcut setup failed: %w", err)
	}
	messageBox("AIOS Setup", "AIOS Manager 已安装。\r\n\r\n长期状态保存在 %USERPROFILE%\\.aios。卸载 Manager 不会删除该目录。", 0x40)
	return exec.Command(managerPath).Start()
}

func atomicInstall(path string, data []byte) error {
	temp, err := os.CreateTemp(filepath.Dir(path), ".aios-setup-*.tmp")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	defer os.Remove(tempPath)
	if _, err := temp.Write(data); err != nil {
		temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempPath, path); err != nil {
		return err
	}
	return nil
}

func createShortcuts(installDir, managerPath string) error {
	script, err := bundle.ReadFile("shortcut.ps1")
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(os.TempDir(), "aios-setup-shortcut-*.ps1")
	if err != nil {
		return err
	}
	path := file.Name()
	defer os.Remove(path)
	if _, err := file.Write(script); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	ps := filepath.Join(os.Getenv("WINDIR"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.Command(ps, "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", path, "-InstallDir", installDir, "-ManagerPath", managerPath)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("PowerShell shortcut registration failed: %w (%s)", err, string(output))
	}
	return nil
}

func messageBox(title, message string, flags uintptr) {
	titlePtr, _ := syscall.UTF16PtrFromString(title)
	messagePtr, _ := syscall.UTF16PtrFromString(message)
	proc := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	proc.Call(0, uintptr(unsafe.Pointer(messagePtr)), uintptr(unsafe.Pointer(titlePtr)), flags)
}
