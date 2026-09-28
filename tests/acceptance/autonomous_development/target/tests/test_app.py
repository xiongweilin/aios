import json

from app import app, create_app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_answer_is_deterministic() -> None:
    response = client.get("/answer", params={"value": "  Hello  "})
    assert response.status_code == 200
    assert response.json() == {"answer": "hello"}


def test_ready_probes_the_reality_root(tmp_path) -> None:
    response = TestClient(create_app(tmp_path)).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert list(tmp_path.iterdir()) == []


def test_task_persists_and_reads_back_reality(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    task = {"task_id": "acceptance-1", "value": "  Hello Reality  "}
    expected = {
        "task_id": "acceptance-1",
        "status": "completed",
        "value": "  Hello Reality  ",
        "result": "hello reality",
    }

    created = client.post("/tasks", json=task)
    readback = client.get("/reality/acceptance-1")

    assert created.status_code == 201
    assert created.json() == expected
    assert readback.status_code == 200
    assert readback.json() == expected
    assert json.loads((tmp_path / "acceptance-1.json").read_text(encoding="utf-8")) == expected


def test_task_id_is_single_use_and_does_not_overwrite_reality(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    first = {"task_id": "single-use", "value": "first"}
    second = {"task_id": "single-use", "value": "second"}

    assert client.post("/tasks", json=first).status_code == 201
    assert client.post("/tasks", json=second).status_code == 409
    assert client.get("/reality/single-use").json()["result"] == "first"


def test_task_id_cannot_escape_reality_root(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post("/tasks", json={"task_id": "../outside", "value": "no"})

    assert response.status_code == 422
    assert not (tmp_path.parent / "outside.json").exists()


def test_missing_reality_is_not_fabricated(tmp_path) -> None:
    response = TestClient(create_app(tmp_path)).get("/reality/unknown")

    assert response.status_code == 404
