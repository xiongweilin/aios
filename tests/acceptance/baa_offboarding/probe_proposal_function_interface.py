#!/usr/bin/env python3
"""Probe whether the local Responses route enforces a forced strict function call.

This is an interface capability probe only. It does not execute the proposed action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any
import urllib.request


FUNCTION_NAME = "submit_baa_proposal"
PARAMETERS = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["execute"]},
        "obligation_id": {"type": "string"},
        "subject_ref": {"type": "string"},
        "target_system": {"type": "string"},
        "operation": {"type": "string"},
        "authority_epoch": {"type": "integer"},
    },
    "required": [
        "kind",
        "obligation_id",
        "subject_ref",
        "target_system",
        "operation",
        "authority_epoch",
    ],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-base", default="http://127.0.0.1:4101")
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    return parser.parse_args()


def decode_response(raw: bytes, content_type: str) -> dict[str, Any]:
    stripped = raw.lstrip()
    is_sse = (
        "text/event-stream" in (content_type or "").lower()
        or stripped.startswith(b"data:")
        or stripped.startswith(b"event:")
    )
    if not is_sse:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Responses body must be an object")
        return value

    completed: dict[str, Any] | None = None
    output_items: dict[int, dict[str, Any]] = {}
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if (
            event_type in {"response.output_item.added", "response.output_item.done"}
            and isinstance(event.get("item"), dict)
            and isinstance(event.get("output_index"), int)
        ):
            output_items[event["output_index"]] = event["item"]
        elif event_type == "response.completed" and isinstance(event.get("response"), dict):
            completed = dict(event["response"])

    if completed is None:
        completed = {"output": []}
    if not completed.get("output") and output_items:
        completed["output"] = [item for _, item in sorted(output_items.items())]
    return completed


def find_function_call(body: dict[str, Any]) -> dict[str, Any]:
    calls = [
        item
        for item in body.get("output") or []
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == FUNCTION_NAME
    ]
    if len(calls) != 1:
        types = [
            item.get("type")
            for item in body.get("output") or []
            if isinstance(item, dict)
        ]
        raise AssertionError(
            f"expected exactly one {FUNCTION_NAME} function_call; "
            f"found={len(calls)} output_types={types}"
        )
    return calls[0]


def parse_arguments(call: dict[str, Any]) -> dict[str, Any]:
    arguments = call.get("arguments")
    if isinstance(arguments, str):
        value = json.loads(arguments)
    elif isinstance(arguments, dict):
        value = arguments
    else:
        raise AssertionError(f"unexpected arguments type: {type(arguments).__name__}")
    if not isinstance(value, dict):
        raise AssertionError("function arguments must decode to an object")
    return value


def validate_arguments(value: dict[str, Any]) -> None:
    required = set(PARAMETERS["required"])
    if set(value) != required:
        raise AssertionError(
            f"function arguments keys differ from strict schema: {sorted(value)}"
        )
    if value["kind"] != "execute":
        raise AssertionError(f"unexpected kind: {value['kind']!r}")
    for key in ("obligation_id", "subject_ref", "target_system", "operation"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise AssertionError(f"{key} must be a non-empty string")
    if isinstance(value["authority_epoch"], bool) or not isinstance(
        value["authority_epoch"], int
    ):
        raise AssertionError("authority_epoch must be an integer")


def main() -> None:
    args = parse_args()
    payload = {
        "model": args.model,
        "input": (
            "Use the submit_baa_proposal function exactly once. "
            "Propose an execute action for obligation obl:identity, "
            "subject employee:probe, target system iam, operation identity.disable, "
            "authority epoch 21. Do not answer with ordinary text."
        ),
        "tools": [
            {
                "type": "function",
                "name": FUNCTION_NAME,
                "description": (
                    "Submit one syntactically valid BAA proposal. "
                    "This probe records arguments only and executes nothing."
                ),
                "parameters": PARAMETERS,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "function", "name": FUNCTION_NAME},
        "parallel_tool_calls": False,
        "stream": False,
        "store": False,
    }
    request = urllib.request.Request(
        f"{args.gateway_base.rstrip('/')}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer baa-function-probe",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    latency = time.perf_counter() - started

    body = decode_response(raw, content_type)
    call = find_function_call(body)
    arguments = parse_arguments(call)
    validate_arguments(arguments)

    evidence = {
        "qualified": True,
        "model_id": args.model,
        "function_name": FUNCTION_NAME,
        "latency_seconds": latency,
        "content_type": content_type,
        "arguments": arguments,
        "output_types": [
            item.get("type")
            for item in body.get("output") or []
            if isinstance(item, dict)
        ],
        "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
