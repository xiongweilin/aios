from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, connect

CodexSandboxName = Literal["read-only", "workspace-write"]
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_PROTOCOL_VERSION = "aios-codex-bridge/1"


class CodexBridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        outcome: Literal["not_started", "failed", "unknown"] = "failed",
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.outcome = outcome


@dataclass(frozen=True, slots=True)
class RemoteCodexTurn:
    request_id: str
    thread_id: str
    turn_id: str
    status: str
    server_version: str
    events: tuple[Mapping[str, object], ...]
    agent_messages: tuple[str, ...]
    result_sha256: str

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True, slots=True)
class _HostPathRoot:
    container: PurePosixPath
    host: PurePosixPath | PureWindowsPath


class HostPathMapper:
    """Map only explicitly shared container roots into their host bind mounts."""

    def __init__(self, roots: tuple[_HostPathRoot, ...]) -> None:
        if not roots:
            raise ValueError("Codex host path map must contain at least one root")
        self._roots = tuple(sorted(roots, key=lambda root: len(root.container.parts), reverse=True))

    @classmethod
    def from_file(cls, path: Path) -> HostPathMapper:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Codex host path map is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Codex host path map must use version 1")
        raw_roots = payload.get("roots")
        if not isinstance(raw_roots, list):
            raise ValueError("Codex host path map roots must be a list")
        roots: list[_HostPathRoot] = []
        for raw in raw_roots:
            if not isinstance(raw, dict):
                raise ValueError("Codex host path map root must be an object")
            container_raw = raw.get("containerRoot")
            host_raw = raw.get("hostRoot")
            if not isinstance(container_raw, str) or not isinstance(host_raw, str):
                raise ValueError("Codex host path map roots require string paths")
            container = PurePosixPath(posixpath.normpath(container_raw))
            if not container.is_absolute():
                raise ValueError("Codex container roots must be absolute")
            host: PurePosixPath | PureWindowsPath
            windows_host = PureWindowsPath(host_raw)
            if windows_host.drive or host_raw.startswith("\\\\"):
                host = windows_host
            else:
                host = PurePosixPath(host_raw)
            if not host.is_absolute():
                raise ValueError("Codex host roots must be absolute")
            roots.append(_HostPathRoot(container, host))
        return cls(tuple(roots))

    def map_path(self, path: str | Path) -> str:
        raw_path = str(path).replace("\\", "/")
        if not raw_path.startswith("/"):
            raise ValueError("Codex container working directory must be absolute")
        normalized = PurePosixPath(posixpath.normpath(raw_path))
        for root in self._roots:
            try:
                relative = normalized.relative_to(root.container)
            except ValueError:
                continue
            return str(root.host.joinpath(*relative.parts))
        raise ValueError("Codex working directory is outside configured host bind mounts")


class RemoteCodexAppServer:
    """Versioned AIOS adapter for a loopback-authenticated Windows Codex server.

    The App Server is an external executor. AIOS journals each request locally and
    never re-dispatches a turn after an ambiguous post-dispatch disconnect.
    """

    def __init__(
        self,
        *,
        url: str,
        token_file: Path,
        path_map_file: Path,
        journal_root: Path,
        client_name: str,
        client_version: str = _PROTOCOL_VERSION,
        connect_timeout_seconds: float = 8.0,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or not parsed.port:
            raise ValueError("Codex App Server URL must be ws(s)://host:port")
        for label, value in (
            ("token_file", token_file),
            ("path_map_file", path_map_file),
            ("journal_root", journal_root),
        ):
            if not value.is_absolute():
                raise ValueError(f"{label} must be absolute")
        if not client_name.strip() or not client_version.strip():
            raise ValueError("Codex App Server client identity must be non-empty")
        if connect_timeout_seconds <= 0:
            raise ValueError("Codex App Server connect timeout must be positive")
        self._url = url
        self._token_file = token_file
        self._path_mapper = HostPathMapper.from_file(path_map_file)
        self._journal_root = journal_root
        self._client_name = client_name
        self._client_version = client_version
        self._connect_timeout_seconds = connect_timeout_seconds

    def health(self) -> str:
        with self._connection() as socket:
            server_version = self._initialize(socket, time.monotonic() + self._connect_timeout_seconds)
            self._notify(socket, "initialized", {})
            return server_version

    def run_turn(
        self,
        *,
        request_id: str,
        prompt: str,
        cwd: str | Path,
        sandbox: CodexSandboxName,
        thread_id: str | None,
        resume_key: str | None,
        model: str | None,
        timeout_seconds: int,
        output_schema: Mapping[str, object] | None = None,
    ) -> RemoteCodexTurn:
        if not _SAFE_REQUEST_ID.fullmatch(request_id):
            raise ValueError("Codex request id contains unsupported characters")
        if not prompt.strip():
            raise ValueError("Codex prompt must be non-empty")
        if timeout_seconds < 1:
            raise ValueError("Codex timeout must be positive")
        host_cwd = self._path_mapper.map_path(cwd)
        marker = f"[AIOS-REQUEST-ID:{request_id}]"
        marked_prompt = f"{marker}\n{prompt}"
        request_digest = _request_digest(
            marked_prompt,
            host_cwd,
            sandbox,
            model,
            output_schema,
        )
        journal_path = self._journal_path(request_id)
        journal = self._read_journal(journal_path, request_id, request_digest)
        if journal is not None:
            journal_thread = _optional_string(journal.get("threadId"))
            if thread_id is not None and journal_thread not in {None, thread_id}:
                raise CodexBridgeError(
                    "Codex request journal thread identity conflicts",
                    request_id=request_id,
                    outcome="unknown",
                )
            journal_state = _string(journal.get("state"), "journal.state")
            if journal_state == "prepared":
                thread_id = journal_thread or thread_id
            elif journal_state == "failed":
                raise CodexBridgeError(
                    "prior Codex request failed; a new request id is required to retry",
                    request_id=request_id,
                    outcome="failed",
                )
            else:
                return self._reconcile_existing(
                    request_id=request_id,
                    request_digest=request_digest,
                    marker=marker,
                    journal=journal,
                    journal_path=journal_path,
                    timeout_seconds=timeout_seconds,
                )

        deadline = time.monotonic() + timeout_seconds
        self._write_journal(
            request_id,
            {
                "version": 1,
                "requestId": request_id,
                "requestDigest": request_digest,
                "threadId": thread_id,
                "turnId": None,
                "state": "prepared",
                "resultSha256": None,
            },
        )
        dispatched = False
        events: list[dict[str, object]] = []
        agent_messages: list[str] = []
        current_thread_id = thread_id
        server_version = ""
        turn_id = ""
        try:
            with self._connection() as socket:
                server_version = self._initialize(socket, deadline)
                self._notify(socket, "initialized", {})
                permission_profile = self._select_permission_profile(
                    socket,
                    sandbox=sandbox,
                    deadline=deadline,
                    events=events,
                )
                if current_thread_id is None:
                    params: dict[str, object] = {
                        "cwd": host_cwd,
                        "approvalPolicy": "never",
                        "sandbox": sandbox,
                        "serviceName": self._client_name,
                    }
                    if model:
                        params["model"] = model
                    thread_result = self._rpc(
                        socket,
                        method="thread/start",
                        request_id=3,
                        params=params,
                        deadline=deadline,
                        events=events,
                        host_cwd=host_cwd,
                        sandbox=sandbox,
                    )
                    thread = _mapping(thread_result.get("thread"), "thread")
                    current_thread_id = _string(thread.get("id"), "thread.id")
                else:
                    thread_result = self._rpc(
                        socket,
                        method="thread/resume",
                        request_id=3,
                        params={"threadId": current_thread_id},
                        deadline=deadline,
                        events=events,
                        host_cwd=host_cwd,
                        sandbox=sandbox,
                    )
                    thread = _mapping(thread_result.get("thread"), "thread")
                    resumed_id = _string(thread.get("id"), "thread.id")
                    if resumed_id != current_thread_id:
                        raise CodexBridgeError("Codex resumed a different thread")
                self._write_journal(
                    request_id,
                    {
                        "version": 1,
                        "requestId": request_id,
                        "requestDigest": request_digest,
                        "threadId": current_thread_id,
                        "turnId": None,
                        "state": "prepared",
                        "resultSha256": None,
                        "serverVersion": server_version,
                    },
                )
                params = {
                    "threadId": current_thread_id,
                    "input": [{"type": "text", "text": marked_prompt}],
                    "cwd": host_cwd,
                    "approvalPolicy": "never",
                    **_sandbox_policy(host_cwd, permission_profile),
                }
                if model:
                    params["model"] = model
                if output_schema is not None:
                    params["outputSchema"] = dict(output_schema)
                self._write_journal(
                    request_id,
                    {
                        "version": 1,
                        "requestId": request_id,
                        "requestDigest": request_digest,
                        "threadId": current_thread_id,
                        "turnId": None,
                        "state": "dispatching",
                        "resultSha256": None,
                        "serverVersion": server_version,
                    },
                )
                dispatched = True
                turn_result = self._rpc(
                    socket,
                    method="turn/start",
                    request_id=4,
                    params=params,
                    deadline=deadline,
                    events=events,
                    host_cwd=host_cwd,
                    sandbox=sandbox,
                )
                turn = _mapping(turn_result.get("turn"), "turn")
                turn_id = _string(turn.get("id"), "turn.id")
                self._write_journal(
                    request_id,
                    {
                        "version": 1,
                        "requestId": request_id,
                        "requestDigest": request_digest,
                        "threadId": current_thread_id,
                        "turnId": turn_id,
                        "state": "running",
                        "resultSha256": None,
                        "serverVersion": server_version,
                    },
                )
                status = self._await_completion(
                    socket,
                    thread_id=current_thread_id,
                    turn_id=turn_id,
                    deadline=deadline,
                    events=events,
                    agent_messages=agent_messages,
                    host_cwd=host_cwd,
                    sandbox=sandbox,
                )
            result_sha256 = _result_digest(
                request_id,
                current_thread_id,
                turn_id,
                status,
                tuple(agent_messages),
            )
            self._write_journal(
                request_id,
                {
                    "version": 1,
                    "requestId": request_id,
                    "requestDigest": request_digest,
                    "threadId": current_thread_id,
                    "turnId": turn_id,
                    "state": "completed" if status == "completed" else "failed",
                    "resultSha256": result_sha256,
                    "serverVersion": server_version,
                },
            )
            if status != "completed":
                raise CodexBridgeError(
                    f"Codex turn ended with status {status}",
                    request_id=request_id,
                    outcome="failed",
                )
            return RemoteCodexTurn(
                request_id=request_id,
                thread_id=current_thread_id,
                turn_id=turn_id,
                status=status,
                server_version=server_version,
                events=tuple(events),
                agent_messages=tuple(agent_messages),
                result_sha256=result_sha256,
            )
        except CodexBridgeError as exc:
            if dispatched:
                self._write_journal(
                    request_id,
                    {
                        "version": 1,
                        "requestId": request_id,
                        "requestDigest": request_digest,
                        "threadId": current_thread_id,
                        "turnId": turn_id or None,
                        "state": "failed" if exc.outcome == "failed" else "unknown",
                        "resultSha256": None,
                        "serverVersion": server_version or None,
                    },
                )
            raise
        except (ConnectionClosed, TimeoutError, OSError, WebSocketException, ValueError) as exc:
            outcome: Literal["not_started", "unknown"] = "unknown" if dispatched else "not_started"
            self._write_journal(
                request_id,
                {
                    "version": 1,
                    "requestId": request_id,
                    "requestDigest": request_digest,
                    "threadId": current_thread_id,
                    "turnId": turn_id or None,
                    "state": "unknown" if dispatched else "not_started",
                    "resultSha256": None,
                    "serverVersion": server_version or None,
                },
            )
            raise CodexBridgeError(
                f"Codex App Server transport failed ({outcome})",
                request_id=request_id,
                outcome=outcome,
            ) from exc

    def _reconcile_existing(
        self,
        *,
        request_id: str,
        request_digest: str,
        marker: str,
        journal: Mapping[str, object],
        journal_path: Path,
        timeout_seconds: int,
    ) -> RemoteCodexTurn:
        state = _string(journal.get("state"), "journal.state")
        if state == "not_started":
            raise CodexBridgeError(
                "prior Codex attempt was not dispatched; a new request id is required to retry",
                request_id=request_id,
                outcome="not_started",
            )
        thread_id = _string(journal.get("threadId"), "journal.threadId")
        expected_turn_id = _optional_string(journal.get("turnId"))
        deadline = time.monotonic() + timeout_seconds
        events: list[dict[str, object]] = []
        messages: list[str] = []
        server_version = ""
        try:
            with self._connection() as socket:
                server_version = self._initialize(socket, deadline)
                self._notify(socket, "initialized", {})
                thread_result = self._rpc(
                    socket,
                    method="thread/read",
                    request_id=2,
                    params={"threadId": thread_id, "includeTurns": True},
                    deadline=deadline,
                    events=events,
                    host_cwd=None,
                    sandbox="read-only",
                )
                thread = _mapping(thread_result.get("thread"), "thread")
                turns = thread.get("turns")
                if not isinstance(turns, list):
                    raise ValueError("thread/read did not return turns")
                matching = _find_turn(turns, marker)
                if matching is None:
                    raise CodexBridgeError(
                        "Codex outcome remains unknown; matching request marker was not found",
                        request_id=request_id,
                        outcome="unknown",
                    )
                turn_id = _string(matching.get("id"), "turn.id")
                if expected_turn_id is not None and turn_id != expected_turn_id:
                    raise CodexBridgeError(
                        "Codex reconciliation found a different turn identity",
                        request_id=request_id,
                        outcome="unknown",
                    )
                status = _string(matching.get("status"), "turn.status")
                if status == "inProgress":
                    self._rpc(
                        socket,
                        method="thread/resume",
                        request_id=3,
                        params={"threadId": thread_id},
                        deadline=deadline,
                        events=events,
                        host_cwd=None,
                        sandbox="read-only",
                    )
                    status = self._await_completion(
                        socket,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        deadline=deadline,
                        events=events,
                        agent_messages=messages,
                        host_cwd=None,
                        sandbox="read-only",
                    )
                else:
                    messages.extend(_agent_messages(matching.get("items")))
                if status != "completed":
                    raise CodexBridgeError(
                        f"reconciled Codex turn is {status}",
                        request_id=request_id,
                        outcome="failed" if status in {"failed", "interrupted"} else "unknown",
                    )
            result_sha256 = _result_digest(
                request_id,
                thread_id,
                turn_id,
                status,
                tuple(messages),
            )
            if journal.get("resultSha256") not in {None, result_sha256}:
                raise CodexBridgeError(
                    "Codex reconciliation result digest differs from the AIOS journal",
                    request_id=request_id,
                    outcome="unknown",
                )
            self._write_journal(
                request_id,
                {
                    "version": 1,
                    "requestId": request_id,
                    "requestDigest": request_digest,
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "state": "completed",
                    "resultSha256": result_sha256,
                    "serverVersion": server_version,
                },
            )
            return RemoteCodexTurn(
                request_id=request_id,
                thread_id=thread_id,
                turn_id=turn_id,
                status=status,
                server_version=server_version,
                events=tuple(events),
                agent_messages=tuple(messages),
                result_sha256=result_sha256,
            )
        except CodexBridgeError:
            raise
        except (ConnectionClosed, TimeoutError, OSError, WebSocketException, ValueError) as exc:
            raise CodexBridgeError(
                "Codex reconciliation is unavailable; outcome remains unknown",
                request_id=request_id,
                outcome="unknown",
            ) from exc

    def _connection(self) -> ClientConnection:
        try:
            token = self._token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CodexBridgeError("Codex App Server transport token is unavailable") from exc
        if not token:
            raise CodexBridgeError("Codex App Server transport token is empty")
        try:
            return connect(
                self._url,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=self._connect_timeout_seconds,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=10,
                max_size=4 * 1024 * 1024,
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise CodexBridgeError("Codex App Server is unreachable") from exc

    def _select_permission_profile(
        self,
        socket: ClientConnection,
        *,
        sandbox: CodexSandboxName,
        deadline: float,
        events: list[dict[str, object]],
    ) -> str:
        requested = ":read-only" if sandbox == "read-only" else ":workspace"
        result = self._rpc(
            socket,
            method="permissionProfile/list",
            request_id=2,
            params={},
            deadline=deadline,
            events=events,
            host_cwd=None,
            sandbox="read-only",
        )
        profiles = result.get("data")
        if not isinstance(profiles, list):
            raise CodexBridgeError("Codex permission profile catalog is malformed")
        if not any(
            isinstance(profile, Mapping)
            and profile.get("id") == requested
            and profile.get("allowed") is True
            for profile in profiles
        ):
            raise CodexBridgeError(
                "required Codex permission profile is unavailable",
                outcome="not_started",
            )
        return requested

    def _initialize(self, socket: ClientConnection, deadline: float) -> str:
        result = self._rpc(
            socket,
            method="initialize",
            request_id=1,
            params={
                "clientInfo": {
                    "name": self._client_name,
                    "title": "AIOS Codex Bridge v1",
                    "version": self._client_version,
                },
                "capabilities": {"experimentalApi": True},
            },
            deadline=deadline,
            events=[],
            host_cwd=None,
            sandbox="read-only",
        )
        server = result.get("serverInfo")
        if isinstance(server, dict):
            name = _string(server.get("name"), "serverInfo.name")
            version = _string(server.get("version"), "serverInfo.version")
            if name.casefold() != "codex":
                raise CodexBridgeError("remote endpoint is not a Codex App Server")
            return version

        user_agent = _string(result.get("userAgent"), "userAgent")
        if "codex" not in user_agent.casefold():
            raise CodexBridgeError("remote endpoint is not a Codex App Server")
        return user_agent

    @staticmethod
    def _notify(socket: ClientConnection, method: str, params: Mapping[str, object]) -> None:
        socket.send(json.dumps({"method": method, "params": dict(params)}, separators=(",", ":")))

    def _rpc(
        self,
        socket: ClientConnection,
        *,
        method: str,
        request_id: int,
        params: Mapping[str, object],
        deadline: float,
        events: list[dict[str, object]],
        host_cwd: str | None,
        sandbox: CodexSandboxName,
    ) -> Mapping[str, object]:
        socket.send(
            json.dumps(
                {"method": method, "id": request_id, "params": dict(params)},
                separators=(",", ":"),
            )
        )
        while True:
            message = self._receive(socket, deadline)
            if message.get("id") == request_id:
                error = message.get("error")
                if error is not None:
                    raise CodexBridgeError(f"Codex RPC failed: {error!r}")
                return _mapping(message.get("result"), "RPC result")
            event_method = message.get("method")
            if not isinstance(event_method, str):
                raise CodexBridgeError("Codex App Server returned an uncorrelated message")
            if "id" in message:
                self._handle_server_request(
                    socket,
                    message,
                    host_cwd=host_cwd,
                    sandbox=sandbox,
                )
            else:
                events.append(message)

    def _await_completion(
        self,
        socket: ClientConnection,
        *,
        thread_id: str,
        turn_id: str,
        deadline: float,
        events: list[dict[str, object]],
        agent_messages: list[str],
        host_cwd: str | None,
        sandbox: CodexSandboxName,
    ) -> str:
        while True:
            message = self._receive(socket, deadline)
            method = message.get("method")
            if not isinstance(method, str):
                continue
            if "id" in message:
                self._handle_server_request(
                    socket,
                    message,
                    host_cwd=host_cwd,
                    sandbox=sandbox,
                )
                continue
            events.append(message)
            params = _mapping(message.get("params", {}), "notification params")
            if method == "item/completed":
                agent_messages.extend(_agent_messages([params.get("item")]))
            elif method == "turn/completed":
                turn = _mapping(params.get("turn"), "completed turn")
                completed_id = _string(turn.get("id"), "completed turn.id")
                if completed_id == turn_id:
                    return _string(turn.get("status"), "completed turn.status")
            elif method == "turn/error":
                raise CodexBridgeError(f"Codex turn failed for thread {thread_id}")

    def _handle_server_request(
        self,
        socket: ClientConnection,
        message: Mapping[str, object],
        *,
        host_cwd: str | None,
        sandbox: CodexSandboxName,
    ) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(request_id, (str, int)) or not isinstance(method, str):
            raise CodexBridgeError("Codex server request is malformed")
        params = _mapping(message.get("params", {}), "server request params")
        if method == "item/fileChange/requestApproval":
            grant_root = params.get("grantRoot")
            accepted = (
                sandbox == "workspace-write"
                and host_cwd is not None
                and _path_within(grant_root, host_cwd)
            )
            result: Mapping[str, object] = {"decision": "accept" if accepted else "decline"}
        elif method == "item/commandExecution/requestApproval":
            command_cwd = params.get("cwd")
            accepted = (
                sandbox == "workspace-write"
                and host_cwd is not None
                and (command_cwd is None or _path_within(command_cwd, host_cwd))
            )
            result = {"decision": "accept" if accepted else "decline"}
        elif method == "item/permissions/requestApproval":
            result = {
                "permissions": {"fileSystem": None, "network": None},
                "scope": "turn",
                "strictAutoReview": True,
            }
        elif method == "item/tool/requestUserInput":
            result = {"answers": {}}
        else:
            socket.send(
                json.dumps(
                    {
                        "id": request_id,
                        "error": {"code": -32601, "message": "Unsupported server request"},
                    },
                    separators=(",", ":"),
                )
            )
            return
        socket.send(
            json.dumps(
                {"id": request_id, "result": dict(result)},
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _receive(socket: ClientConnection, deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Codex request timed out")
        message = socket.recv(timeout=remaining)
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        parsed = json.loads(message)
        if not isinstance(parsed, dict):
            raise ValueError("Codex App Server returned a non-object message")
        return parsed

    def _journal_path(self, request_id: str) -> Path:
        if not _SAFE_REQUEST_ID.fullmatch(request_id):
            raise ValueError("Codex request id contains unsupported characters")
        safe_request_id = os.path.basename(request_id)
        if safe_request_id != request_id:
            raise ValueError("Codex request id must be a filename component")
        digest = hashlib.sha256(safe_request_id.encode("utf-8")).hexdigest()
        journal_root = self._journal_root.resolve()
        journal_directory = (journal_root / "remote-requests").resolve()
        if not journal_directory.is_relative_to(journal_root):
            raise ValueError("Codex request journal directory escapes its configured root")
        path = (journal_directory / f"{digest}.json").resolve()
        if not path.is_relative_to(journal_directory):
            raise ValueError("Codex request journal path escapes its configured directory")
        return path

    def _read_journal(
        self,
        path: Path,
        request_id: str,
        request_digest: str,
    ) -> Mapping[str, object] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CodexBridgeError("AIOS Codex request journal is unreadable") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("requestId") != request_id
            or payload.get("requestDigest") != request_digest
        ):
            raise CodexBridgeError(
                "Codex request id is already bound to different request content",
                request_id=request_id,
                outcome="unknown",
            )
        return payload

    def _write_journal(self, request_id: str, payload: Mapping[str, object]) -> None:
        path = self._journal_path(request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        try:
            temporary.write_text(  #NOSONAR(S2083)
                json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as exc:
            raise CodexBridgeError("AIOS Codex request journal could not be persisted") from exc
        finally:
            temporary.unlink(missing_ok=True)


def _request_digest(
    prompt: str,
    cwd: str,
    sandbox: CodexSandboxName,
    model: str | None,
    output_schema: Mapping[str, object] | None,
) -> str:
    payload = {
        "prompt": prompt,
        "cwd": cwd,
        "sandbox": sandbox,
        "model": model,
        "output_schema": dict(output_schema) if output_schema is not None else None,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _result_digest(
    request_id: str,
    thread_id: str,
    turn_id: str,
    status: str,
    messages: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "requestId": request_id,
            "threadId": thread_id,
            "turnId": turn_id,
            "status": status,
            "agentMessages": messages,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sandbox_policy(cwd: str, profile: str) -> dict[str, object]:
    return {
        "permissions": profile,
        "runtimeWorkspaceRoots": [cwd],
    }


def _find_turn(turns: list[object], marker: str) -> Mapping[str, object] | None:
    for raw_turn in reversed(turns):
        if not isinstance(raw_turn, Mapping):
            continue
        items = raw_turn.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping) or item.get("type") != "userMessage":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            if any(
                isinstance(part, Mapping)
                and isinstance(part.get("text"), str)
                and marker in part["text"]
                for part in content
            ):
                return raw_turn
    return None


def _agent_messages(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    messages: list[str] = []
    for item in items:
        if not isinstance(item, Mapping) or item.get("type") not in {"agentMessage", "agent_message"}:
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            messages.append(text)
    return messages


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CodexBridgeError(f"{name} must be an object")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CodexBridgeError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _path_within(value: object, root: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        child = PureWindowsPath(value)
        parent = PureWindowsPath(root)
        return child == parent or parent in child.parents
    except (TypeError, ValueError):
        return False
