//go:build windows && product

package main

import (
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"

	"github.com/xiongweilin/aios/internal/profile"
)

//go:embed product-ui.ps1
var productUIScript string

func main() {
	if err := ensureAIOSHome(); err != nil {
		showProductMessage("AIOS Manager", err.Error(), 0x10)
		os.Exit(1)
	}
	args := os.Args[1:]
	var err error
	if len(args) == 0 {
		err = showProductUI(productUIScript)
	} else {
		err = executeProductCommand(args)
	}
	if err != nil {
		showProductMessage("AIOS Manager", err.Error(), 0x10)
		os.Exit(1)
	}
}

func showProductMessage(title, message string, flags uintptr) uintptr {
	titlePtr, _ := syscall.UTF16PtrFromString(title)
	messagePtr, _ := syscall.UTF16PtrFromString(message)
	proc := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	result, _, _ := proc.Call(0, uintptr(unsafe.Pointer(messagePtr)), uintptr(unsafe.Pointer(titlePtr)), flags)
	return result
}

func showProductUI(script string) error {
	file, err := os.CreateTemp(os.TempDir(), "aios-manager-*.ps1")
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
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	ps := filepath.Join(os.Getenv("WINDIR"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.Command(ps, "-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", path, "-ManagerPath", exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}

func executeProductCommand(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("usage: aios.exe install | update | start | stop | status | logs | repair | uninstall")
	}
	root, _ := aiosHome()
	switch args[0] {
	case "status":
		profilePath := filepath.Join(root, "config", "release-profile.json")
		data, err := os.ReadFile(profilePath)
		if os.IsNotExist(err) {
			showProductMessage("AIOS 状态", "Manager 已安装。尚无已发布的兼容 profile；未安装组件、未执行启动或更新。长期目录："+root, 0x40)
			return nil
		}
		if err != nil {
			return err
		}
		profile, err := profile.ParseReleaseProfile(data)
		if err != nil {
			showProductMessage("AIOS 状态", "本地 profile 无效，未执行任何生命周期操作：\r\n"+err.Error(), 0x30)
			return nil
		}
		showProductMessage("AIOS 状态", fmt.Sprintf("已验证 profile %s；组件生命周期暂未开放。长期目录：%s", profile.Version, root), 0x40)
		return nil
	case "logs":
		return exec.Command("explorer.exe", filepath.Join(root, "logs")).Start()
	case "uninstall":
		return uninstallProductManager()
	case "install", "update", "start", "stop", "repair":
		return fmt.Errorf("%s 暂不可用：没有已发布并通过兼容验证的 AIOS profile；未改动文件或服务。查看 https://github.com/xiongweilin/aios/releases", args[0])
	default:
		return fmt.Errorf("unknown command %q; use status, logs, install, update, start, stop, repair, or uninstall", args[0])
	}
}

func uninstallProductManager() error {
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return fmt.Errorf("LOCALAPPDATA is not set")
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	installDir := filepath.Dir(exe)
	expected := filepath.Join(localAppData, "Programs", "Metratio", "AIOS")
	if !sameWindowsPath(installDir, expected) {
		return fmt.Errorf("refusing to uninstall from unexpected location %s", installDir)
	}
	if showProductMessage("卸载 AIOS Manager", "移除 Manager 程序和快捷方式？\r\n%USERPROFILE%\\.aios 中的 config、state、data、logs、components 与 domains 都会保留。", 0x24) != 6 {
		return nil
	}
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Metratio", "AIOS.lnk")
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop", "AIOS.lnk")
	psScript := `$ErrorActionPreference='SilentlyContinue'; Start-Sleep -Seconds 2; Remove-Item -LiteralPath $args[0] -Recurse -Force; Remove-Item -LiteralPath $args[1] -Force; Remove-Item -LiteralPath $args[2] -Force; Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MetratioAIOS' -Recurse -Force; Remove-Item -LiteralPath $PSCommandPath -Force`
	file, err := os.CreateTemp(os.TempDir(), "aios-uninstall-*.ps1")
	if err != nil {
		return err
	}
	path := file.Name()
	if _, err := file.WriteString(psScript); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	ps := filepath.Join(os.Getenv("WINDIR"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.Command(ps, "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", path, installDir, startMenu, desktop)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err != nil {
		os.Remove(path)
		return err
	}
	return nil
}

func sameWindowsPath(left, right string) bool {
	leftAbs, errLeft := filepath.Abs(left)
	rightAbs, errRight := filepath.Abs(right)
	return errLeft == nil && errRight == nil && strings.EqualFold(filepath.Clean(leftAbs), filepath.Clean(rightAbs))
}
