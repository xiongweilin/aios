package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const webURL = "https://aios.metratio.com"

type service struct {
	id       string
	label    string
	port     int
	health   string
	root     string
	category string
}

var services = []service{
	{id: "litellm-gateway", label: "LiteLLM Gateway", port: 4101, root: `D:\agent\litellm-gateway`, category: "dependency"},
	{id: "world-runtime", label: "World Runtime", port: 18086, health: "http://127.0.0.1:18086/healthz", root: `D:\agent\world-runtime`, category: "dependency"},
	{id: "personal-world", label: "Personal World", port: 8000, root: `D:\agent\personal-world`, category: "dependency"},
	{id: "control-plane", label: "Control Plane", port: 18083, health: "http://127.0.0.1:18083/live", root: `D:\agent\control-plane`, category: "domain"},
	{id: "administrative-orchestrator", label: "Administrative Orchestrator", root: `D:\infrastructure\compose\administrative-orchestrator`, category: "domain"},
	{id: "autonomous-development", label: "Autonomous Development", port: 8765, root: `D:\agent\autonomous-development`, category: "domain"},
}

func defaultEntryServices() []service {
	return []service{
		{id: "agency-console-bff", label: "Agency Console BFF", port: 8787, root: `D:\agent\agency-console`},
		{id: "agency-console-web", label: "Agency Console Web", port: 3000, health: "http://127.0.0.1:3000/", root: `D:\agent\agency-console`},
	}
}

type processRef struct {
	PID        int    `json:"pid"`
	Creation   uint64 `json:"creationFileTime"`
	Executable string `json:"executable"`
}

type runState struct {
	Processes map[string]processRef `json:"processes"`
}

var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	procCreateMutex     = kernel32.NewProc("CreateMutexW")
	procWaitForSingle   = kernel32.NewProc("WaitForSingleObject")
	procReleaseMutex    = kernel32.NewProc("ReleaseMutex")
	procCloseHandle     = kernel32.NewProc("CloseHandle")
	procOpenProcess     = kernel32.NewProc("OpenProcess")
	procGetProcessTimes = kernel32.NewProc("GetProcessTimes")
	mutexName           = `Local\Metratio.AIOS.ServiceController`
	processQueryLimited = uintptr(0x1000)
	waitObject0         = uintptr(0)
	waitAbandoned       = uintptr(0x80)
	waitFailed          = uintptr(0xFFFFFFFF)
)

func stateDir() (string, error) {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		return "", errors.New("LOCALAPPDATA is not set")
	}
	return filepath.Join(base, "Metratio", "AIOS"), nil
}

func ensureStateDir() (string, error) {
	dir, err := stateDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Join(dir, "logs"), 0700); err != nil {
		return "", err
	}
	return dir, nil
}

func processStatePath() (string, error) {
	dir, err := ensureStateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "processes.json"), nil
}

func profilePath() (string, error) {
	dir, err := ensureStateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "profile.json"), nil
}

func logPath(id string) (string, error) {
	dir, err := ensureStateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "logs", id+".log"), nil
}

func atomicWrite(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".aios-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func loadState() (runState, error) {
	path, err := processStatePath()
	if err != nil {
		return runState{}, err
	}
	state := runState{Processes: map[string]processRef{}}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, nil
	}
	if err != nil {
		return state, err
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return state, fmt.Errorf("read AIOS process state: %w", err)
	}
	if state.Processes == nil {
		state.Processes = map[string]processRef{}
	}
	return state, nil
}

func saveState(state runState) error {
	path, err := processStatePath()
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	return atomicWrite(path, data)
}

func saveProfile(ids []string) error {
	valid := map[string]bool{}
	for _, s := range services {
		valid[s.id] = true
	}
	unique := make([]string, 0, len(ids))
	seen := map[string]bool{}
	for _, id := range ids {
		if !valid[id] {
			return fmt.Errorf("unknown service ID %q", id)
		}
		if !seen[id] {
			seen[id] = true
			unique = append(unique, id)
		}
	}
	data, err := json.MarshalIndent(unique, "", "  ")
	if err != nil {
		return err
	}
	path, err := profilePath()
	if err != nil {
		return err
	}
	return atomicWrite(path, data)
}

func readProfile() ([]string, error) {
	path, err := profilePath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		ids := make([]string, 0, len(services))
		for _, s := range services {
			ids = append(ids, s.id)
		}
		return ids, nil
	}
	if err != nil {
		return nil, err
	}
	var ids []string
	if err := json.Unmarshal(data, &ids); err != nil {
		return nil, fmt.Errorf("read AIOS profile: %w", err)
	}
	return ids, nil
}

func acquireMutex() (func(), error) {
	name, err := syscall.UTF16PtrFromString(mutexName)
	if err != nil {
		return nil, err
	}
	h, _, callErr := procCreateMutex.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if h == 0 {
		return nil, callErr
	}
	wait, _, waitErr := procWaitForSingle.Call(h, uintptr(0xFFFFFFFF))
	if wait == waitFailed {
		procCloseHandle.Call(h)
		return nil, waitErr
	}
	if wait != waitObject0 && wait != waitAbandoned {
		procCloseHandle.Call(h)
		return nil, fmt.Errorf("unexpected mutex wait result %#x", wait)
	}
	return func() {
		procReleaseMutex.Call(h)
		procCloseHandle.Call(h)
	}, nil
}

func execute(verb string, args []string) error {
	switch verb {
	case "profile":
		if len(args) == 0 || args[0] == "get" {
			ids, err := readProfile()
			if err != nil {
				return err
			}
			for _, id := range ids {
				fmt.Println(id)
			}
			return nil
		}
		if args[0] == "save" {
			return saveProfile(args[1:])
		}
		return errors.New("usage: aios.exe profile get | profile save [service-id ...]")
	case "start", "stop":
		ids, all, err := parseSelection(args)
		if err != nil {
			return err
		}
		if all {
			ids = allServiceIDs()
		}
		release, err := acquireMutex()
		if err != nil {
			return err
		}
		defer release()
		if verb == "start" {
			return startServices(ids)
		}
		return stopServices(ids)
	case "status":
		ids, all, err := parseSelection(args)
		if err != nil {
			return err
		}
		if all {
			ids = allServiceIDs()
		}
		return showStatus(ids)
	case "logs":
		if len(args) == 0 || args[0] == "--default-only" {
			return openLogsFolder()
		}
		return showLogs(args)
	default:
		return fmt.Errorf("unknown command %q; use start, stop, status, or logs", verb)
	}
}

func parseSelection(args []string) ([]string, bool, error) {
	if len(args) == 0 {
		return nil, true, nil
	}
	if len(args) == 1 && args[0] == "--default-only" {
		return nil, false, nil
	}
	valid := map[string]bool{}
	for _, s := range services {
		valid[s.id] = true
	}
	unique := []string{}
	seen := map[string]bool{}
	for _, id := range args {
		if !valid[id] {
			return nil, false, fmt.Errorf("unknown service ID %q", id)
		}
		if !seen[id] {
			seen[id] = true
			unique = append(unique, id)
		}
	}
	return unique, false, nil
}

func allServiceIDs() []string {
	ids := make([]string, 0, len(services))
	for _, s := range services {
		ids = append(ids, s.id)
	}
	return ids
}

func serviceByID(id string) (service, bool) {
	for _, s := range services {
		if s.id == id {
			return s, true
		}
	}
	return service{}, false
}

func startServices(ids []string) error {
	selected := map[string]bool{}
	for _, id := range ids {
		selected[id] = true
	}
	effective := map[string]bool{}
	for id, isSelected := range selected {
		effective[id] = isSelected
	}
	if selected["control-plane"] {
		effective["world-runtime"] = true
	}
	state, err := loadState()
	if err != nil {
		return err
	}
	var failures []string
	startedAny := false
	for _, s := range services {
		if !effective[s.id] {
			continue
		}
		message, err := startOne(s, &state)
		if !selected[s.id] {
			message = "[自动依赖] " + message
		}
		fmt.Println(message)
		if err != nil {
			failures = append(failures, fmt.Sprintf("%s: %v", s.label, err))
		} else {
			startedAny = true
		}
	}
	for _, entry := range defaultEntryServices() {
		message, err := startOne(entry, &state)
		fmt.Printf("[默认] %s\n", message)
		if err != nil {
			failures = append(failures, fmt.Sprintf("%s: %v", entry.label, err))
		} else {
			startedAny = true
		}
	}
	if err := saveState(state); err != nil {
		failures = append(failures, "save process state: "+err.Error())
	}
	if startedAny {
		entries := defaultEntryServices()
		if !waitForService(entries[0], 20*time.Second) {
			failures = append(failures, "Agency Console BFF did not become reachable on 127.0.0.1:8787")
		} else if !waitForService(entries[1], 45*time.Second) {
			failures = append(failures, "Agency Console Web did not become ready on 127.0.0.1:3000; browser was not opened")
		} else {
			openBrowser()
		}
	}
	if len(failures) > 0 {
		return errors.New(strings.Join(failures, "; "))
	}
	return nil
}

func stopServices(ids []string) error {
	selected := map[string]bool{}
	for _, id := range ids {
		selected[id] = true
	}
	state, err := loadState()
	if err != nil {
		return err
	}
	var failures []string
	entries := defaultEntryServices()
	for i := len(entries) - 1; i >= 0; i-- {
		entry := entries[i]
		if err := stopOne(entry, &state); err != nil {
			fmt.Printf("[默认] %s: %v\n", entry.label, err)
			failures = append(failures, fmt.Sprintf("%s: %v", entry.label, err))
		} else {
			fmt.Printf("[默认] %s 已关闭或未由 AIOS 托管。\n", entry.label)
		}
	}
	for i := len(services) - 1; i >= 0; i-- {
		s := services[i]
		if !selected[s.id] {
			continue
		}
		message, err := stopOneMessage(s, &state)
		fmt.Println(message)
		if err != nil {
			failures = append(failures, fmt.Sprintf("%s: %v", s.label, err))
		}
	}
	if err := saveState(state); err != nil {
		failures = append(failures, "save process state: "+err.Error())
	}
	if len(failures) > 0 {
		return errors.New(strings.Join(failures, "; "))
	}
	return nil
}

func startOne(s service, state *runState) (string, error) {
	if (s.id == "agency-console-bff" || s.id == "agency-console-web") && tcpOpen(s.port) {
		pid, ok, err := findServiceListener(s)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", fmt.Errorf("port %d is occupied by a process that is not verified as %s; left unchanged", s.port, s.label)
		}
		created, err := processCreationTime(uint32(pid))
		if err != nil || created == 0 {
			return "", fmt.Errorf("%s is reachable, but its process identity could not be recorded", s.label)
		}
		state.Processes[s.id] = processRef{PID: pid, Creation: created, Executable: "node.exe"}
		return s.label + " 已在运行；已识别并纳入默认关闭管理。", nil
	}
	if s.health != "" && httpOK(s.health) || s.port > 0 && tcpOpen(s.port) {
		return s.label + " 已在运行；跳过重复启动。", nil
	}
	if ref, ok := state.Processes[s.id]; ok && processMatches(ref) {
		return s.label + " 已由 AIOS 启动；跳过重复启动。", nil
	}
	switch s.id {
	case "litellm-gateway":
		uv, err := exec.LookPath("uv.exe")
		if err != nil {
			return "", fmt.Errorf("uv.exe was not found on PATH")
		}
		project := filepath.Join(s.root, "litellm")
		server := filepath.Join(project, "run_server.py")
		config := filepath.Join(project, "config.runtime.yaml")
		pid, err := startTracked(s, state, uv, []string{"run", "--no-sync", "--project", project, "python", server, "--config", config, "--host", "127.0.0.1", "--port", "4101"}, project)
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	case "world-runtime":
		uv, err := exec.LookPath("uv.exe")
		if err != nil {
			return "", fmt.Errorf("uv.exe was not found on PATH")
		}
		dataDir, err := stateDir()
		if err != nil {
			return "", err
		}
		dataDir = filepath.Join(dataDir, "data")
		if err := os.MkdirAll(dataDir, 0700); err != nil {
			return "", err
		}
		stateDB := filepath.Join(dataDir, "world-runtime.db")
		program := fmt.Sprintf("import uvicorn; from world_runtime.ledger import SQLiteLedger; from world_runtime.runtime import WorldRuntime; from world_runtime.service import create_app; ledger = SQLiteLedger(r'%s'); app = create_app(WorldRuntime(ledger, runtime_id='world-runtime')); uvicorn.run(app, host='127.0.0.1', port=18086, log_level='warning')", stateDB)
		pid, err := startTracked(s, state, uv, []string{"run", "--no-sync", "--project", s.root, "python", "-c", program}, s.root)
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	case "personal-world":
		uv, err := exec.LookPath("uv.exe")
		if err != nil {
			return "", fmt.Errorf("uv.exe was not found on PATH")
		}
		pid, err := startTracked(s, state, uv, []string{"run", "--no-sync", "--project", s.root, "uvicorn", "personal_world.api.app:app", "--host", "127.0.0.1", "--port", "8000"}, s.root)
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	case "control-plane":
		uv, err := exec.LookPath("uv.exe")
		if err != nil {
			return "", fmt.Errorf("uv.exe was not found on PATH")
		}
		pid, err := startElevated(s, state, uv, []string{"run", "--no-sync", "--project", s.root, "control-plane"}, s.root)
		return fmt.Sprintf("%s 启动中（PID %d；如需权限，已请求 UAC）。", s.label, pid), err
	case "administrative-orchestrator":
		out, err := runLogged(s.id, s.root, "docker.exe", "compose", "-f", "compose.yaml", "up", "-d")
		return loggedMessage(s.label, out, err)
	case "autonomous-development":
		uv, err := exec.LookPath("uv.exe")
		if err != nil {
			return "", fmt.Errorf("uv.exe was not found on PATH")
		}
		for _, name := range []string{"AUTODEV_DATABASE_URL", "AUTODEV_DBOS_SYSTEM_DATABASE_URL", "AUTODEV_STATE_ROOT"} {
			if _, ok := os.LookupEnv(name); !ok {
				return "", fmt.Errorf("required environment variable %s is not set", name)
			}
		}
		programData := os.Getenv("ProgramData")
		secretFile := filepath.Join(programData, "AutonomousDevelopment", "secrets", "operator_hmac_secret")
		if _, err := os.Stat(secretFile); err != nil {
			return "", fmt.Errorf("Autonomous Development operator secret file is missing")
		}
		pid, err := startTrackedWithEnv(s, state, uv, []string{"run", "--no-sync", "--project", s.root, "autonomous-development", "serve"}, s.root, []string{
			"AUTODEV_API_HOST=127.0.0.1",
			"AUTODEV_API_PORT=8765",
			"AUTODEV_OPERATOR_HMAC_SECRET_FILE=" + secretFile,
		})
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	case "agency-console-bff":
		pid, err := startTracked(s, state, "cmd.exe", []string{"/d", "/s", "/c", "npm run dev:bff"}, s.root)
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	case "agency-console-web":
		pid, err := startTracked(s, state, "cmd.exe", []string{"/d", "/s", "/c", "npm run dev"}, s.root)
		return fmt.Sprintf("%s 启动中（PID %d）。", s.label, pid), err
	default:
		return "", fmt.Errorf("no start command is configured for %s", s.id)
	}
}

func stopOne(s service, state *runState) error {
	_, err := stopOneMessage(s, state)
	return err
}

func stopOneMessage(s service, state *runState) (string, error) {
	if s.id == "administrative-orchestrator" {
		out, err := runLogged(s.id+"-stop", s.root, "docker.exe", "compose", "-f", "compose.yaml", "stop")
		return loggedMessage(s.label+" stop", out, err)
	}
	if s.id == "world-runtime" && serviceReachable(service{id: "control-plane", port: 18083, health: "http://127.0.0.1:18083/live"}) {
		return s.label + " 未关闭。", errors.New("Control Plane is still active and supervises World Runtime; select Control Plane too")
	}
	ref, ok := state.Processes[s.id]
	if (!ok || !processMatches(ref)) && serviceReachable(s) {
		if ok {
			delete(state.Processes, s.id)
		}
		pid, verified, err := findServiceListener(s)
		if err != nil {
			return s.label + " 未关闭。", err
		}
		if !verified {
			return s.label + " 未关闭。", fmt.Errorf("port %d is occupied, but the process is not verified as %s", s.port, s.label)
		}
		created, err := processCreationTime(uint32(pid))
		if err != nil || created == 0 {
			return s.label + " 未关闭。", fmt.Errorf("could not verify the %s process identity", s.label)
		}
		ref = processRef{PID: pid, Creation: created}
		state.Processes[s.id] = ref
		ok = true
	}
	if !ok {
		return s.label + " 已停止。", nil
	}
	if !processMatches(ref) {
		delete(state.Processes, s.id)
		if serviceReachable(s) {
			return s.label + " 存在外部运行实例；未关闭。", nil
		}
		return s.label + " 已停止。", nil
	}
	if err := killTree(ref.PID); err != nil {
		return s.label + " 关闭失败。", err
	}
	delete(state.Processes, s.id)
	return s.label + " 已关闭。", nil
}

func startTracked(s service, state *runState, program string, args []string, dir string) (int, error) {
	return startTrackedWithEnv(s, state, program, args, dir, nil)
}

func startTrackedWithEnv(s service, state *runState, program string, args []string, dir string, extraEnv []string) (int, error) {
	path, err := logPath(s.id)
	if err != nil {
		return 0, err
	}
	log, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return 0, err
	}
	cmd := exec.Command(program, args...)
	cmd.Dir = dir
	if len(extraEnv) > 0 {
		cmd.Env = mergeEnvironment(os.Environ(), extraEnv)
	}
	cmd.Stdout = log
	cmd.Stderr = log
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err != nil {
		log.Close()
		return 0, err
	}
	_ = log.Close()
	created := uint64(0)
	for i := 0; i < 20; i++ {
		created, _ = processCreationTime(uint32(cmd.Process.Pid))
		if created != 0 {
			break
		}
		time.Sleep(25 * time.Millisecond)
	}
	if created == 0 {
		_ = cmd.Process.Kill()
		return 0, errors.New("could not record process identity; process was terminated")
	}
	state.Processes[s.id] = processRef{PID: cmd.Process.Pid, Creation: created, Executable: program}
	_ = cmd.Process.Release()
	return cmd.Process.Pid, nil
}

func mergeEnvironment(base, overrides []string) []string {
	values := make(map[string]string, len(base)+len(overrides))
	for _, entry := range base {
		if at := strings.IndexByte(entry, '='); at > 0 {
			values[strings.ToUpper(entry[:at])] = entry
		}
	}
	for _, entry := range overrides {
		if at := strings.IndexByte(entry, '='); at > 0 {
			values[strings.ToUpper(entry[:at])] = entry
		}
	}
	result := make([]string, 0, len(values))
	for _, entry := range values {
		result = append(result, entry)
	}
	return result
}

func startElevated(s service, state *runState, program string, args []string, dir string) (int, error) {
	stdout, err := logPath(s.id)
	if err != nil {
		return 0, err
	}
	stderr := strings.TrimSuffix(stdout, ".log") + ".err.log"
	quotePS := func(value string) string { return "'" + strings.ReplaceAll(value, "'", "''") + "'" }
	quotedArgs := make([]string, 0, len(args))
	for _, arg := range args {
		quotedArgs = append(quotedArgs, quotePS(arg))
	}
	command := fmt.Sprintf("$p = Start-Process -FilePath %s -ArgumentList @(%s) -WorkingDirectory %s -Verb RunAs -PassThru -WindowStyle Hidden -RedirectStandardOutput %s -RedirectStandardError %s; [Console]::Out.WriteLine($p.Id)", quotePS(program), strings.Join(quotedArgs, ","), quotePS(dir), quotePS(stdout), quotePS(stderr))
	ps, err := exec.LookPath("powershell.exe")
	if err != nil {
		return 0, err
	}
	cmd := exec.Command(ps, "-NoProfile", "-Command", command)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	var output bytes.Buffer
	cmd.Stdout = &output
	if err := cmd.Run(); err != nil {
		return 0, fmt.Errorf("UAC launch failed or was declined: %w (%s)", err, strings.TrimSpace(output.String()))
	}
	lines := strings.Fields(output.String())
	if len(lines) == 0 {
		return 0, errors.New("elevated launcher returned no process ID")
	}
	pid, err := strconv.Atoi(lines[len(lines)-1])
	if err != nil {
		return 0, fmt.Errorf("parse elevated process ID: %w", err)
	}
	created, _ := processCreationTime(uint32(pid))
	if created == 0 {
		return 0, errors.New("could not record elevated process identity")
	}
	state.Processes[s.id] = processRef{PID: pid, Creation: created, Executable: program}
	return pid, nil
}

func runLogged(id, dir, program string, args ...string) (string, error) {
	path, err := logPath(id)
	if err != nil {
		return "", err
	}
	log, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return "", err
	}
	defer log.Close()
	cmd := exec.Command(program, args...)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	var output bytes.Buffer
	writer := io.MultiWriter(log, &output)
	cmd.Stdout = writer
	cmd.Stderr = writer
	if err := cmd.Run(); err != nil {
		return output.String(), err
	}
	return output.String(), nil
}

func loggedMessage(label, output string, err error) (string, error) {
	message := label + " 已提交。"
	if strings.TrimSpace(output) != "" {
		message += "\n" + strings.TrimSpace(output)
	}
	if err != nil {
		return message, err
	}
	return message, nil
}

func showStatus(ids []string) error {
	state, err := loadState()
	if err != nil {
		return err
	}
	for _, id := range ids {
		s, ok := serviceByID(id)
		if !ok {
			return fmt.Errorf("unknown service ID %q", id)
		}
		status := "stopped"
		if s.id == "administrative-orchestrator" {
			out, err := runLogged("status-"+s.id, s.root, "docker.exe", "compose", "-f", "compose.yaml", "ps", "--status", "running", "--quiet")
			if err != nil {
				status = "unknown (Docker unavailable)"
			} else if strings.TrimSpace(out) != "" {
				status = "running"
			}
		} else if serviceReachable(s) {
			status = "running"
			if ref, ok := state.Processes[s.id]; ok && processMatches(ref) {
				status = "running (AIOS)"
			}
		} else if ref, ok := state.Processes[s.id]; ok && processMatches(ref) {
			status = "process running; health not confirmed"
		}
		fmt.Printf("%-30s %s\n", s.label, status)
	}
	for _, entry := range defaultEntryServices() {
		status := "stopped"
		if serviceReachable(entry) {
			status = "running"
			if ref, ok := state.Processes[entry.id]; ok && processMatches(ref) {
				status = "running (AIOS)"
			}
		}
		fmt.Printf("%-30s %s [default]\n", entry.label, status)
	}
	return nil
}

func waitForService(s service, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		ready := serviceReachable(s)
		if s.id == "agency-console-web" {
			ready = s.health != "" && httpOK(s.health)
		}
		if ready {
			return true
		}
		time.Sleep(300 * time.Millisecond)
	}
	if s.id == "agency-console-web" {
		return s.health != "" && httpOK(s.health)
	}
	return serviceReachable(s)
}

func serviceReachable(s service) bool {
	if s.health != "" && httpOK(s.health) {
		return true
	}
	return s.port > 0 && tcpOpen(s.port)
}

func findServiceListener(s service) (int, bool, error) {
	ps, err := exec.LookPath("powershell.exe")
	if err != nil {
		return 0, false, err
	}
	match := ""
	switch s.id {
	case "world-runtime":
		match = `$p.CommandLine -match 'world_runtime|18086'`
	case "personal-world":
		match = `$p.CommandLine -match 'personal_world\.api\.app'`
	case "litellm-gateway":
		match = `$p.CommandLine -match 'run_server\.py'`
	case "control-plane":
		match = `$p.CommandLine -match 'control_plane|control-plane'`
	case "autonomous-development":
		match = `$p.CommandLine -match 'autonomous_development|autonomous-development'`
	case "agency-console-bff":
		match = `$p.Name -eq 'node.exe' -and $p.CommandLine -like '*D:\agent\agency-console*'`
	case "agency-console-web":
		match = `$p.Name -eq 'node.exe' -and $p.CommandLine -like '*D:\agent\agency-console*' -and $p.CommandLine -like '*next*dev*'`
	default:
		return 0, false, fmt.Errorf("no process identity rule exists for %s", s.id)
	}
	command := fmt.Sprintf(`$listeners = Get-NetTCPConnection -State Listen -LocalPort %d -ErrorAction SilentlyContinue; foreach ($listener in $listeners) { $p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $listener.OwningProcess); if ($null -ne $p -and (%s)) { [Console]::Out.WriteLine($p.ProcessId); exit 0 } }; exit 3`, s.port, match)
	cmd := exec.Command(ps, "-NoProfile", "-Command", command)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 3 {
			return 0, false, nil
		}
		return 0, false, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(output)))
	if err != nil || pid <= 0 {
		return 0, false, fmt.Errorf("could not parse the verified %s process ID", s.label)
	}
	return pid, true, nil
}

func httpOK(url string) bool {
	client := http.Client{Timeout: 700 * time.Millisecond}
	response, err := client.Get(url)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode >= 200 && response.StatusCode < 400
}

func tcpOpen(port int) bool {
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 250*time.Millisecond)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func processCreationTime(pid uint32) (uint64, error) {
	h, _, openErr := procOpenProcess.Call(processQueryLimited, 0, uintptr(pid))
	if h == 0 {
		return 0, openErr
	}
	defer procCloseHandle.Call(h)
	var creation, exit, kernel, user syscall.Filetime
	result, _, callErr := procGetProcessTimes.Call(h, uintptr(unsafe.Pointer(&creation)), uintptr(unsafe.Pointer(&exit)), uintptr(unsafe.Pointer(&kernel)), uintptr(unsafe.Pointer(&user)))
	if result == 0 {
		return 0, callErr
	}
	return uint64(creation.HighDateTime)<<32 | uint64(creation.LowDateTime), nil
}

func processMatches(ref processRef) bool {
	if ref.PID <= 0 || ref.Creation == 0 {
		return false
	}
	created, err := processCreationTime(uint32(ref.PID))
	return err == nil && created == ref.Creation
}

func killTree(pid int) error {
	cmd := exec.Command("taskkill.exe", "/PID", strconv.Itoa(pid), "/T", "/F")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := cmd.CombinedOutput()
	if err == nil {
		return nil
	}
	ps, findErr := exec.LookPath("powershell.exe")
	if findErr != nil {
		return fmt.Errorf("taskkill failed: %w (%s)", err, strings.TrimSpace(string(output)))
	}
	command := fmt.Sprintf("$p = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID','%d','/T','/F') -Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode", pid)
	elevated := exec.Command(ps, "-NoProfile", "-Command", command)
	elevated.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if elevatedErr := elevated.Run(); elevatedErr != nil {
		return fmt.Errorf("taskkill failed (%s); elevated stop failed or was declined: %w", strings.TrimSpace(string(output)), elevatedErr)
	}
	return nil
}

func openBrowser() {
	cmd := exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", webURL)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Start()
	if cmd.Process != nil {
		_ = cmd.Process.Release()
	}
}

func openLogsFolder() error {
	dir, err := ensureStateDir()
	if err != nil {
		return err
	}
	cmd := exec.Command("explorer.exe", filepath.Join(dir, "logs"))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Start()
}

func showLogs(ids []string) error {
	for _, id := range ids {
		s, ok := serviceByID(id)
		if !ok {
			return fmt.Errorf("unknown service ID %q", id)
		}
		if id == "administrative-orchestrator" {
			out, err := runLogged("logs-"+id, s.root, "docker.exe", "compose", "-f", "compose.yaml", "logs", "--tail", "200")
			if err != nil {
				return err
			}
			fmt.Print(out)
			continue
		}
		path, err := logPath(id)
		if err != nil {
			return err
		}
		cmd := exec.Command("notepad.exe", path)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		if err := cmd.Start(); err != nil {
			return err
		}
		_ = cmd.Process.Release()
	}
	return nil
}
