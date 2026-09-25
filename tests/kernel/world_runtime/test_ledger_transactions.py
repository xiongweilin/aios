import pytest

from world_runtime.ledger import SQLiteLedger


def test_semantic_transaction_rolls_back_event_and_projection_together() -> None:
    ledger = SQLiteLedger()
    with pytest.raises(RuntimeError, match="boom"):
        with ledger.transaction():
            ledger.project_put("demo", "item", {"status": "changed"})
            ledger.append(
                stream="demo:item",
                kind="demo.changed",
                payload={"status": "changed"},
            )
            raise RuntimeError("boom")

    assert ledger.project_get("demo", "item") is None
    assert ledger.events(stream="demo:item") == []


def test_semantic_transaction_supports_nested_service_writes() -> None:
    ledger = SQLiteLedger()
    with ledger.transaction():
        ledger.project_put("demo", "item", {"status": "one"})
        with ledger.transaction():
            current = ledger.project_get("demo", "item")
            assert current is not None
            ledger.project_put(
                "demo",
                "item",
                {"status": "two"},
                expected_version=current[1],
            )
        ledger.append(
            stream="demo:item",
            kind="demo.changed",
            payload={"status": "two"},
        )

    current = ledger.project_get("demo", "item")
    assert current is not None
    assert current[0]["status"] == "two"
    assert len(ledger.events(stream="demo:item")) == 1


def test_file_backed_sqlite_projection_cas_has_one_winner(tmp_path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from world_runtime.ledger import ProjectionVersionConflict

    path = tmp_path / "shared-ledger.db"
    first = SQLiteLedger(path)
    second = SQLiteLedger(path)
    try:
        assert first.project_put("demo", "item", {"winner": None}, expected_version=0) == 1
        barrier = Barrier(2)

        def update(ledger: SQLiteLedger, winner: str) -> str:
            barrier.wait()
            try:
                ledger.project_put(
                    "demo",
                    "item",
                    {"winner": winner},
                    expected_version=1,
                )
                return winner
            except ProjectionVersionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: update(*args),
                    [(first, "a"), (second, "b")],
                )
            )

        assert results.count("conflict") == 1
        winner = next(value for value in results if value != "conflict")
        current = first.project_get("demo", "item")
        assert current is not None
        assert current[0] == {"winner": winner}
        assert current[1] == 2
    finally:
        first.close()
        second.close()
