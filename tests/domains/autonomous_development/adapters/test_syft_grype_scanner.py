from pathlib import Path

from autonomous_development.adapters.evidence import LocalEvidenceStore
from autonomous_development.adapters.supply_chain import SyftGrypeScanner
from autonomous_development.ports.process import CommandRequest, CommandResult


class FakeScanRunner:
    def __init__(self, grype_returncode: int) -> None:
        self.grype_returncode = grype_returncode
        self.requests: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        if request.command[0] == "syft":
            output_arg = request.command[request.command.index("-o") + 1]
            output_path = Path(output_arg.split("=", 1)[1])
            output_path.write_text(
                '{"bomFormat":"CycloneDX","components":[]}',
                encoding="utf-8",
            )
            return CommandResult(returncode=0, stdout="", stderr="")
        if request.command[0] == "grype":
            output_path = Path(request.command[request.command.index("--file") + 1])
            output_path.write_text('{"matches":[]}', encoding="utf-8")
            return CommandResult(
                returncode=self.grype_returncode,
                stdout="",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {request.command}")


class WindowsContainerFallbackRunner:
    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        command = request.command
        if command[0] == "syft":
            return CommandResult(
                returncode=1,
                stdout="",
                stderr=(
                    "rename ... docker-tarball-image ...: "
                    "The parameter is incorrect."
                ),
            )
        if command[:2] == ("docker", "save"):
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_bytes(b"docker archive")
            return CommandResult(returncode=0, stdout="", stderr="")
        if command[:2] == ("docker", "run"):
            volume = command[command.index("--volume") + 1]
            host_root = Path(volume.removesuffix(":/work"))
            if any("anchore/syft@" in part for part in command):
                (host_root / "sbom.cdx.json").write_text(
                    '{"bomFormat":"CycloneDX","components":[]}',
                    encoding="utf-8",
                )
            elif any("anchore/grype@" in part for part in command):
                (host_root / "grype.json").write_text(
                    '{"matches":[]}',
                    encoding="utf-8",
                )
            else:
                raise AssertionError(f"unexpected scanner image: {command}")
            return CommandResult(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")


def test_supply_chain_scan_passes_without_threshold_violation(tmp_path: Path) -> None:
    scanner = SyftGrypeScanner(
        FakeScanRunner(grype_returncode=0),
        LocalEvidenceStore((tmp_path / "evidence").resolve()),
    )
    result = scanner.scan("sha256:" + "a" * 64, candidate_id="candidate-1")
    assert result.passed
    assert result.sbom_digest.startswith("sha256:")
    assert result.sbom_ref.startswith("file:")
    assert result.vulnerability_scan_ref.startswith("file:")


def test_supply_chain_scan_records_threshold_failure(tmp_path: Path) -> None:
    scanner = SyftGrypeScanner(
        FakeScanRunner(grype_returncode=2),
        LocalEvidenceStore((tmp_path / "evidence").resolve()),
        fail_on="high",
    )
    result = scanner.scan("sha256:" + "a" * 64, candidate_id="candidate-1")
    assert not result.passed


def test_windows_layer_cache_failure_uses_pinned_container_scanners(
    tmp_path: Path,
) -> None:
    runner = WindowsContainerFallbackRunner()
    scanner = SyftGrypeScanner(
        runner,
        LocalEvidenceStore((tmp_path / "evidence").resolve()),
        platform_name="nt",
    )

    result = scanner.scan("sha256:" + "a" * 64, candidate_id="candidate-1")

    assert result.passed
    commands = [request.command for request in runner.requests]
    assert commands[0][0] == "syft"
    assert any(command[:2] == ("docker", "save") for command in commands)
    assert any(
        command[:2] == ("docker", "run")
        and any("anchore/syft@sha256:" in part for part in command)
        for command in commands
    )
    assert any(
        command[:2] == ("docker", "run")
        and any("anchore/grype@sha256:" in part for part in command)
        for command in commands
    )
