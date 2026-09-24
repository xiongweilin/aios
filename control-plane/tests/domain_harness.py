from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from control_plane.domain_controller import PersonalController
from control_plane.domain_store import DomainJournal
from control_plane.provider_protocol import CapabilityProvider, ProviderRegistry
from control_plane.runtime_bridge import PersonalRuntimeBridge, WorldRuntimeClient
from tests.runtime_stub import RuntimeStub


@dataclass
class DomainHarness:
    stub: RuntimeStub
    journal: DomainJournal
    providers: ProviderRegistry
    client: WorldRuntimeClient
    controller: PersonalController
    bridge: PersonalRuntimeBridge

    def close(self) -> None:
        self.client.close()
        self.journal.close()


def make_harness(
    tmp_path: Path,
    *,
    providers: Iterable[CapabilityProvider] = (),
    owner_principal: str = "principal:test",
) -> DomainHarness:
    stub = RuntimeStub()
    journal = DomainJournal(tmp_path / "control-plane-domain.db")
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    client = WorldRuntimeClient(
        "http://world-runtime",
        transport=stub.transport(),
    )
    client.ensure_contracts()
    controller = PersonalController(journal, registry)
    bridge = PersonalRuntimeBridge(
        client,
        controller,
        journal,
        registry,
        owner_principal=owner_principal,
    )
    return DomainHarness(
        stub=stub,
        journal=journal,
        providers=registry,
        client=client,
        controller=controller,
        bridge=bridge,
    )
