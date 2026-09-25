from __future__ import annotations

import signal
import sys
import time

from .config import get_settings
from .messaging import (
    claim_outbox,
    mark_dispatched,
    mark_retry,
    recover_expired_leases,
)
from .persistence import SqlStore

_stop = False


def _request_stop(signum: int, frame: object) -> None:
    del signum, frame
    global _stop
    _stop = True


def relay_once(store: SqlStore) -> tuple[int, int, int]:
    """Recover stale claims and dispatch one bounded outbox batch."""
    from .workflows.relay import dispatch_outbox_event

    settings = get_settings()
    recovered = recover_expired_leases(store, batch=settings.outbox_batch)
    events = claim_outbox(
        store,
        batch=settings.outbox_batch,
        lease_seconds=settings.outbox_lease_seconds,
    )
    dispatched = 0
    failed = 0
    for event in events:
        try:
            dispatch_outbox_event(event)
        except Exception as exc:  # noqa: BLE001 - one poison event must not stop the worker
            mark_retry(
                store,
                event.event_id,
                str(exc),
                max_attempts=settings.outbox_max_attempts,
            )
            failed += 1
        else:
            mark_dispatched(store, event.event_id)
            dispatched += 1
    return recovered, dispatched, failed


def run_forever(store: SqlStore) -> None:
    settings = get_settings()
    while not _stop:
        relay_once(store)
        time.sleep(max(0.05, settings.worker_poll_seconds))


def main() -> int:
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)

    try:
        from .workflows.bootstrap import start_dbos

        start_dbos()
    except Exception as exc:  # noqa: BLE001 - bootstrap failure must fail the process
        print(f"DBOS worker bootstrap failed: {exc}", file=sys.stderr)
        return 1

    try:
        run_forever(store)
    finally:
        try:
            from dbos import DBOS

            DBOS.destroy()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide exit
            print(f"DBOS worker cleanup failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
