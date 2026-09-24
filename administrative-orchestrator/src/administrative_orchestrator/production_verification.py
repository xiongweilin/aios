from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def complete_readback_postcondition(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Complete provider readback with frozen execution-context payload.

    Some effect verifiers independently observe only the external state they
    own (for example, ``active=False``).  The obligation payload is still
    required in the durable evidence view so later semantic verification can
    bind that state to the frozen employment episode and termination facts.
    A provider-returned payload always wins, so an observed mismatch remains
    visible.
    """
    completed = dict(observed or {})
    expected_payload = expected.get("payload")
    if isinstance(expected_payload, dict) and "payload" not in completed:
        completed["payload"] = dict(expected_payload)
    return completed


def readback_satisfies_expected(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
) -> bool:
    """Require every frozen expectation while allowing evidence-only fields.

    Production verifiers may append provider evidence such as an external
    message reference.  Those fields are useful in durable evidence but are
    not additional business postconditions; only the frozen expected keys
    determine the objective result.
    """

    if observed is None:
        return False
    return all(observed.get(key) == value for key, value in expected.items())
