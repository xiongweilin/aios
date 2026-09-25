from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _bounded_dbos_destroy(monkeypatch):
    """Fully drain DBOS integration-test executors before temporary DB deletion.

    DBOS 2.31.1 deliberately calls ``ThreadPoolExecutor.shutdown(wait=False)``
    during ``DBOS.destroy()``. A workflow blocked in ``DBOS.recv`` can therefore
    leave its fallback ``recv_check`` future running for a short interval after
    the singleton has been destroyed. If the test immediately drops its system
    database, DBOS's retry wrapper sees a retriable connection failure and that
    non-daemon executor thread retries forever; Python then waits for it during
    interpreter shutdown.

    The restart integration owns the temporary databases, so its teardown must
    preserve them until every executor future has quiesced. Capture the exact
    executor before destroy, let DBOS close its normal runtime resources, then
    wait for that already-shutdown executor to finish while the database still
    exists. Production lifecycle behavior is unchanged.
    """
    if os.getenv("ADMIN_RUN_DBOS_INTEGRATION") != "1":
        yield
        return

    from dbos import DBOS
    from dbos._dbos import _get_dbos_instance
    from dbos._error import DBOSException

    original_destroy = DBOS.destroy

    def destroy(*args, **kwargs):
        try:
            instance = _get_dbos_instance()
            executor = instance._executor_field
        except DBOSException:
            executor = None

        result = original_destroy(*args, **kwargs)
        if executor is not None:
            # DBOS.destroy() has already issued shutdown(wait=False). Calling
            # shutdown again with wait=True is supported by ThreadPoolExecutor
            # and drains any recv/check future before the owning test drops DBs.
            executor.shutdown(wait=True, cancel_futures=True)
        return result

    monkeypatch.setattr(DBOS, "destroy", staticmethod(destroy))
    yield
