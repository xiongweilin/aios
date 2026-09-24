from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from autonomous_development.ports.build import (
    SupplyChainEvidence,
    SupplyChainScanError,
    SupplyChainScanner,
)
from autonomous_development.ports.evidence import EvidenceStore
from autonomous_development.ports.process import CommandRequest, ProcessRunner

_SYFT_CONTAINER_IMAGE = (
    "anchore/syft@sha256:500e2d872ac019436926e8322b4fc1f39441d94d21f6f4046c6ff29b30e8cb02"
)
_GRYPE_CONTAINER_IMAGE = (
    "anchore/grype@sha256:8c2c9234a345577a6d321a4753aa3ee1276d8975c8452d2344a56b57733ecad3"
)


class _WindowsScannerCompatibilityError(RuntimeError):
    pass


class SyftGrypeScanner(SupplyChainScanner):
    def __init__(
        self,
        runner: ProcessRunner,
        evidence: EvidenceStore,
        *,
        fail_on: str = "high",
        timeout_seconds: int = 900,
        platform_name: str | None = None,
    ) -> None:
        if fail_on not in {"negligible", "low", "medium", "high", "critical"}:
            raise ValueError("unsupported Grype severity threshold")
        self._runner = runner
        self._evidence = evidence
        self._fail_on = fail_on
        self._timeout_seconds = timeout_seconds
        self._platform_name = platform_name or os.name

    def scan(self, image_digest: str, *, candidate_id: str) -> SupplyChainEvidence:
        if not image_digest.startswith("sha256:"):
            raise SupplyChainScanError("scanner requires a sha256 image identity")
        with tempfile.TemporaryDirectory(prefix="autodev-scan-") as directory:
            root = Path(directory)
            sbom_path = root / "sbom.cdx.json"
            grype_path = root / "grype.json"

            try:
                sbom_bytes, grype_bytes, passed = self._scan_with_host_tools(
                    image_digest,
                    root,
                    sbom_path,
                    grype_path,
                )
                scanner_execution: dict[str, str] = {"transport": "host"}
            except _WindowsScannerCompatibilityError:
                sbom_bytes, grype_bytes, passed = self._scan_with_container_tools(
                    image_digest,
                    root,
                    sbom_path,
                    grype_path,
                )
                scanner_execution = {
                    "transport": "docker-container",
                    "syft_image": _SYFT_CONTAINER_IMAGE,
                    "grype_image": _GRYPE_CONTAINER_IMAGE,
                }

            sbom = _json_object(sbom_bytes, "Syft SBOM")
            sbom_digest = "sha256:" + hashlib.sha256(sbom_bytes).hexdigest()
            sbom_ref = self._evidence.write_json(
                "sbom",
                candidate_id,
                {
                    "candidate_id": candidate_id,
                    "image_digest": image_digest,
                    "sbom_digest": sbom_digest,
                    "scanner_execution": scanner_execution,
                    "document": sbom,
                },
            )

            report = _json_object(grype_bytes, "Grype report")
            scan_ref = self._evidence.write_json(
                "vulnerability-scan",
                candidate_id,
                {
                    "candidate_id": candidate_id,
                    "image_digest": image_digest,
                    "fail_on": self._fail_on,
                    "passed": passed,
                    "sbom_ref": sbom_ref,
                    "scanner_execution": scanner_execution,
                    "report": report,
                },
            )
            return SupplyChainEvidence(
                sbom_digest=sbom_digest,
                sbom_ref=sbom_ref,
                vulnerability_scan_ref=scan_ref,
                passed=passed,
            )

    def _scan_with_host_tools(
        self,
        image_digest: str,
        root: Path,
        sbom_path: Path,
        grype_path: Path,
    ) -> tuple[bytes, bytes, bool]:
        syft = self._runner.run(
            CommandRequest(
                command=(
                    "syft",
                    "scan",
                    image_digest,
                    "-o",
                    f"cyclonedx-json={sbom_path}",
                ),
                cwd=root,
                timeout_seconds=self._timeout_seconds,
            )
        )
        if syft.returncode != 0 or not sbom_path.exists():
            if self._is_windows_compatibility_failure(syft):
                raise _WindowsScannerCompatibilityError from None
            raise SupplyChainScanError(
                f"Syft failed with exit {syft.returncode}: {syft.stderr}"
            )
        sbom_bytes = sbom_path.read_bytes()

        grype = self._runner.run(
            CommandRequest(
                command=(
                    "grype",
                    image_digest,
                    "-o",
                    "json",
                    "--file",
                    str(grype_path),
                    "--fail-on",
                    self._fail_on,
                ),
                cwd=root,
                timeout_seconds=self._timeout_seconds,
            )
        )
        if grype.returncode not in {0, 2} or not grype_path.exists():
            if self._is_windows_compatibility_failure(grype):
                raise _WindowsScannerCompatibilityError from None
            raise SupplyChainScanError(
                f"Grype failed with exit {grype.returncode}: {grype.stderr}"
            )
        return sbom_bytes, grype_path.read_bytes(), grype.returncode == 0

    def _scan_with_container_tools(
        self,
        image_digest: str,
        root: Path,
        sbom_path: Path,
        grype_path: Path,
    ) -> tuple[bytes, bytes, bool]:
        archive_path = root / "image.tar"
        save = self._runner.run(
            CommandRequest(
                command=(
                    "docker",
                    "save",
                    image_digest,
                    "-o",
                    str(archive_path),
                ),
                cwd=root,
                timeout_seconds=self._timeout_seconds,
            )
        )
        if save.returncode != 0 or not archive_path.exists():
            raise SupplyChainScanError(
                f"docker save failed with exit {save.returncode}: {save.stderr}"
            )

        volume = f"{root}:/work"
        syft = self._runner.run(
            CommandRequest(
                command=(
                    "docker",
                    "run",
                    "--rm",
                    "--volume",
                    volume,
                    _SYFT_CONTAINER_IMAGE,
                    "scan",
                    "docker-archive:/work/image.tar",
                    "-o",
                    "cyclonedx-json=/work/sbom.cdx.json",
                ),
                cwd=root,
                timeout_seconds=self._timeout_seconds,
            )
        )
        if syft.returncode != 0 or not sbom_path.exists():
            raise SupplyChainScanError(
                f"container Syft failed with exit {syft.returncode}: {syft.stderr}"
            )

        grype = self._runner.run(
            CommandRequest(
                command=(
                    "docker",
                    "run",
                    "--rm",
                    "--volume",
                    volume,
                    _GRYPE_CONTAINER_IMAGE,
                    "docker-archive:/work/image.tar",
                    "-o",
                    "json",
                    "--file",
                    "/work/grype.json",
                    "--fail-on",
                    self._fail_on,
                ),
                cwd=root,
                timeout_seconds=self._timeout_seconds,
            )
        )
        if grype.returncode not in {0, 2} or not grype_path.exists():
            raise SupplyChainScanError(
                f"container Grype failed with exit {grype.returncode}: {grype.stderr}"
            )
        return sbom_path.read_bytes(), grype_path.read_bytes(), grype.returncode == 0

    def _is_windows_compatibility_failure(self, result: object) -> bool:
        if self._platform_name != "nt":
            return False
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        text = f"{stdout}\n{stderr}".lower()
        return "parameter is incorrect" in text and (
            "docker-tarball-image" in text or "rename" in text
        )


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise SupplyChainScanError(f"{label} must be a JSON object")
    return parsed
