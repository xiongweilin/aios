from __future__ import annotations

from typing import Any
from uuid import uuid5

from .commitment_common import M9_NAMESPACE, CommitmentIntakeError, ResponsibilityRefs
from .commitment_models import CommitmentRecord
from .config import Settings
from .domain import AdministrativeCase
from .integrations.world_runtime import WorldRuntimeBoundaryError, WorldRuntimeBridge


class WorldRuntimeCommitmentResponsibilityProvisioner:
    """Provision one standing Runtime responsibility for an admitted commitment."""

    def __init__(self, store, *, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def provision(
        self,
        *,
        case: AdministrativeCase,
        commitment: CommitmentRecord,
        governance_basis: Any,
    ) -> ResponsibilityRefs:
        if case.policy_ref is None:
            raise CommitmentIntakeError("Runtime responsibility requires a current policy")
        if self.settings.world_runtime_mode == "disabled":
            raise CommitmentIntakeError("World Runtime responsibility provisioning is disabled")
        root = uuid5(M9_NAMESPACE, f"world-runtime-responsibility:{commitment.commitment_id}")
        responsibility_ref = f"m9resp_{root.hex}"
        bridge = WorldRuntimeBridge(self.store, self.settings)
        try:
            bridge.provision_responsibility(
                responsibility_ref=responsibility_ref,
                principal=commitment.committer_principal_id,
                subject=commitment.commitment_action,
                scope={
                    "administrative_case_id": str(case.case_id),
                    "authority_epoch": case.authority_epoch,
                    "commitment_ref": str(commitment.commitment_id),
                    "governance_basis_id": str(governance_basis.basis_id),
                    "policy_ref": (
                        f"{case.policy_ref.policy_id}:{case.policy_ref.version}"
                    ),
                    "due_at": commitment.due_at.isoformat(),
                },
            )
        except WorldRuntimeBoundaryError as exc:
            raise CommitmentIntakeError(
                "World Runtime responsibility was not recorded"
            ) from exc
        finally:
            bridge.close()
        return ResponsibilityRefs(
            responsibility_ref=responsibility_ref,
            responsibility_version=1,
        )


__all__ = ["WorldRuntimeCommitmentResponsibilityProvisioner"]
