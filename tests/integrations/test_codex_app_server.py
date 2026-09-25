from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from websockets.sync.server import ServerConnection, serve

from integrations.codex_app_server import CodexBridgeError, RemoteCodexAppServer


class FakeAppServer:
    def __init__(
        self,
        *,
        lose_turn_result: bool = False,
        user_agent_initialize: bool = False,
    ) -> None:
        self.lose_turn_result = lose_turn_result
        self.user_agent_initialize = user_agent_initialize
        self.messages: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []
        self._lock = threading.Lock()

        def process_request(
            connection: ServerConnection,
            request: object,
        ) -> object | None:
            headers = getattr(request, "headers")
            if headers.get("Authorization") != "Bearer test-transport-token":
                return connection.respond(401, "unauthorized")
            return None

        self.server = serve(
            self._handle,
            "127.0.0.1",
            0,
            process_request=process_request,
        )
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)

    def _handle(self, connection: ServerConnection) -> None:
        for raw in connection:
            message = json.loads(raw)
            method = message.get("method")
            with self._lock:
                self.messages.append(dict(message))

            if method == "initialize":
                result = (
                    {
                        "userAgent": "Codex CLI/0.154.0 (Windows; x86_64)"
                    }
                    if self.user_agent_initialize
                    else {"serverInfo": {"name": "codex", "version": "0.154.0"}}
                )
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": result,
                        }
                    )
                )
            elif method == "initialized":
                continue
            elif method == "permissionProfile/list":
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {
                                "data": [
                                    {"id": ":read-only", "allowed": True},
                                    {"id": ":workspace", "allowed": True},
                                ]
                            },
                        }
                    )
                )
            elif method in {"thread/start", "thread/resume"}:
                thread_id = (
                    "thread-test"
                    if method == "thread/start"
                    else message["params"]["threadId"]
                )
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"thread": {"id": thread_id}},
                        }
                    )
                )
            elif method == "turn/start":
                params = message["params"]
                prompt = params["input"][0]["text"]
                turn = {
                    "id": "turn-test",
                    "status": "completed",
                    "items": [
                        {
                            "type": "userMessage",
                            "content": [{"type": "text", "text": prompt}],
                        },
                        {"type": "agentMessage", "text": "verified-result"},
                    ],
                }
                if not self.lose_turn_result:
                    with self._lock:
                        self.turns.append(turn)
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"turn": {"id": "turn-test", "status": "inProgress"}},
                        }
                    )
                )
                if self.lose_turn_result:
                    connection.close()
                    return
                connection.send(
                    json.dumps(
                        {
                            "method": "item/completed",
                            "params": {
                                "item": {"type": "agentMessage", "text": "verified-result"}
                            },
                        }
                    )
                )
                connection.send(
                    json.dumps(
                        {
                            "method": "turn/completed",
                            "params": {
                                "turn": {"id": "turn-test", "status": "completed"}
                            },
                        }
                    )
                )
            elif method == "thread/read":
                with self._lock:
                    turns = list(self.turns)
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"thread": {"id": "thread-test", "turns": turns}},
                        }
                    )
                )
            elif method == "turn/interrupt":
                connection.send(json.dumps({"id": message["id"], "result": {}}))
            else:
                connection.send(
                    json.dumps(
                        {
                            "id": message.get("id"),
                            "error": {"code": -32601, "message": "unsupported"},
                        }
                    )
                )


def _client(tmp_path: Path, server: FakeAppServer) -> RemoteCodexAppServer:
    token = tmp_path / "transport-token"
    token.write_text("test-transport-token", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mapping = tmp_path / "path-map.json"
    mapping.write_text(
        json.dumps(
            {
                "version": 1,
                "roots": [
                    {
                        "containerRoot": "/workspace",
                        "hostRoot": str(workspace),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return RemoteCodexAppServer(
        url=f"ws://127.0.0.1:{server.port}",
        token_file=token.resolve(),
        path_map_file=mapping.resolve(),
        journal_root=(tmp_path / "aios-state").resolve(),
        client_name="aios-test",
    )


def test_health_accepts_codex_cli_user_agent_initialize_response(tmp_path: Path) -> None:
    server = FakeAppServer(user_agent_initialize=True)
    try:
        assert _client(tmp_path, server).health() == "Codex CLI/0.154.0 (Windows; x86_64)"
    finally:
        server.close()


def test_remote_turn_uses_authenticated_jsonrpc_and_reconciles_cached_identity(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    try:
        client = _client(tmp_path, server)
        result = client.run_turn(
            request_id="autodev:cycle-1:implementation-1",
            prompt="make the change",
            cwd="/workspace",
            sandbox="workspace-write",
            thread_id=None,
            resume_key="cycle-1:implementation",
            model="gpt-test",
            timeout_seconds=2,
        )
        replay = client.run_turn(
            request_id="autodev:cycle-1:implementation-1",
            prompt="make the change",
            cwd="/workspace",
            sandbox="workspace-write",
            thread_id=None,
            resume_key="cycle-1:implementation",
            model="gpt-test",
            timeout_seconds=2,
        )

        assert result.completed
        assert result.server_version == "0.154.0"
        initialize = next(message for message in server.messages if message.get("method") == "initialize")
        assert initialize["params"]["capabilities"]["experimentalApi"] is True
        assert result.agent_messages == ("verified-result",)
        assert replay.result_sha256 == result.result_sha256
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
        thread_read = next(message for message in server.messages if message.get("method") == "thread/read")
        assert thread_read["params"]["includeTurns"] is True
        turn_start = next(message for message in server.messages if message.get("method") == "turn/start")
        assert turn_start["params"]["cwd"].endswith("workspace")
        assert turn_start["params"]["permissions"] == ":workspace"
        assert turn_start["params"]["runtimeWorkspaceRoots"] == [str(tmp_path / "workspace")]
        assert "sandboxPolicy" not in turn_start["params"]
        assert "AIOS-REQUEST-ID:autodev:cycle-1:implementation-1" in turn_start["params"]["input"][0]["text"]
    finally:
        server.close()


def test_read_only_turn_uses_restricted_profile_and_only_mapped_workspace_root(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    try:
        result = _client(tmp_path, server).run_turn(
            request_id="autodev:readonly-smoke",
            prompt="respond only with a short confirmation",
            cwd="/workspace",
            sandbox="read-only",
            thread_id=None,
            resume_key=None,
            model=None,
            timeout_seconds=2,
        )
        turn_start = next(message for message in server.messages if message.get("method") == "turn/start")
        assert result.completed
        assert turn_start["params"]["permissions"] == ":read-only"
        assert turn_start["params"]["runtimeWorkspaceRoots"] == [str(tmp_path / "workspace")]
        assert "sandboxPolicy" not in turn_start["params"]
    finally:
        server.close()


def test_remote_turn_marks_lost_completion_unknown_and_does_not_redispatch(
    tmp_path: Path,
) -> None:
    server = FakeAppServer(lose_turn_result=True)
    try:
        client = _client(tmp_path, server)
        kwargs = {
            "request_id": "control-plane:request-1",
            "prompt": "inspect only",
            "cwd": "/workspace",
            "sandbox": "read-only",
            "thread_id": None,
            "resume_key": "control-plane:run-1",
            "model": None,
            "timeout_seconds": 2,
        }
        with pytest.raises(CodexBridgeError) as error:
            client.run_turn(**kwargs)
        assert error.value.outcome == "unknown"

        with pytest.raises(CodexBridgeError) as replay_error:
            client.run_turn(**kwargs)
        assert replay_error.value.outcome == "unknown"
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
    finally:
        server.close()


def test_path_mapper_rejects_unmounted_container_worktree(tmp_path: Path) -> None:
    server = FakeAppServer()
    try:
        client = _client(tmp_path, server)
        with pytest.raises(ValueError, match="outside configured host bind mounts"):
            client.run_turn(
                request_id="invalid-path",
                prompt="no-op",
                cwd=Path("/unmounted/repository"),
                sandbox="read-only",
                thread_id=None,
                resume_key=None,
                model=None,
                timeout_seconds=1,
            )
    finally:
        server.close()
