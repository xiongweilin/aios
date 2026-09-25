from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityPolicy:
    capability: str
    impact_class: str
    resource_required: bool
    version_required: bool


CAPABILITY_POLICIES: tuple[CapabilityPolicy, ...] = (
    CapabilityPolicy("shell.exec", "write-local", True, False),
    CapabilityPolicy("notify.send", "write-remote", False, False),
    CapabilityPolicy("git.merge", "write-local", True, True),
    CapabilityPolicy("git.push", "write-remote", True, True),
    CapabilityPolicy("git.fast_forward", "write-local", True, True),
    CapabilityPolicy("git.push_exact_ref", "write-remote", True, True),
    CapabilityPolicy("git.discard_line_ending_changes", "write-local", True, False),
    CapabilityPolicy("chezmoi.apply", "write-local", True, True),
    CapabilityPolicy("git.rollback", "write-local", True, True),
    CapabilityPolicy("docker.restart", "write-local", True, False),
    CapabilityPolicy("docker.compose.up", "write-local", True, False),
    CapabilityPolicy("maintenance.cleanup_known_garbage", "write-local", True, False),
)


def capability_policy(capability: str) -> CapabilityPolicy | None:
    return next(
        (item for item in CAPABILITY_POLICIES if item.capability == capability),
        None,
    )


__all__ = ["CAPABILITY_POLICIES", "CapabilityPolicy", "capability_policy"]
