from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve

_TOKEN_FILE = Path(os.environ["AIOS_ACCEPTANCE_CODEX_TOKEN_FILE"])
_PORT = 18786


async def handle_connection(connection: ServerConnection, token: str) -> None:
    if connection.request.headers.get("Authorization") != f"Bearer {token}":
        await connection.close(code=4401, reason="unauthorized")
        return
    async for raw_message in connection:
        message = json.loads(raw_message)
        method = message.get("method")
        if method == "initialize":
            await connection.send(
                json.dumps(
                    {
                        "id": message.get("id"),
                        "result": {
                            "serverInfo": {"name": "codex", "version": "acceptance-stub"}
                        },
                    }
                )
            )
        elif method != "initialized" and "id" in message:
            await connection.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": "method is not implemented by the acceptance stub",
                        },
                    }
                )
            )


async def main() -> None:
    token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("acceptance Codex token is empty")

    async def handler(connection: ServerConnection) -> None:
        await handle_connection(connection, token)

    async with serve(handler, "0.0.0.0", _PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
