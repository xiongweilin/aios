from __future__ import annotations

import argparse

from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.authority_lifecycle import AuthorityLifecycleRepository
from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import Principal
from administrative_orchestrator.persistence import SqlStore

PROVIDER = "https://dr-idp.example.test"
SUBJECT = "dr-subject"
PRINCIPAL_ID = "person:dr-proof"


def seed(store: SqlStore) -> None:
    authority = AuthorityRepository(store)
    lifecycle = AuthorityLifecycleRepository(store)
    authority.put_principal(Principal(principal_id=PRINCIPAL_ID, display_name="DR Proof"))
    if authority.resolve_identity(provider=PROVIDER, external_subject=SUBJECT) is None:
        lifecycle.bind_identity(
            IdentityBinding(
                provider=PROVIDER,
                external_subject=SUBJECT,
                principal_id=PRINCIPAL_ID,
            ),
            actor_principal_id=PRINCIPAL_ID,
            reason="M5 backup/restore acceptance fixture",
        )


def verify(store: SqlStore) -> None:
    authority = AuthorityRepository(store)
    lifecycle = AuthorityLifecycleRepository(store)
    principal = authority.resolve_identity(provider=PROVIDER, external_subject=SUBJECT)
    if principal is None or principal.principal_id != PRINCIPAL_ID:
        raise RuntimeError("restored PostgreSQL state lost authoritative identity binding")
    events = lifecycle.list_events(limit=100)
    if not any(
        event.event_type == "identity_binding.created"
        and event.payload.get("principal_id") == PRINCIPAL_ID
        for event in events
    ):
        raise RuntimeError("restored PostgreSQL state lost authority lifecycle history")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "verify"))
    args = parser.parse_args()
    store = SqlStore(get_settings().database_url)
    if args.mode == "seed":
        seed(store)
    else:
        verify(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
