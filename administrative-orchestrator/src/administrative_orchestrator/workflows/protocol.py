"""Pure durable-workflow protocol constants shared with the outbox relay."""

CASE_CHANGED_TOPIC = "case_changed"
NORMAL_WAKE_TIMEOUT_SECONDS = 3600
RECONCILIATION_POLL_SECONDS = 30

__all__ = [
    "CASE_CHANGED_TOPIC",
    "NORMAL_WAKE_TIMEOUT_SECONDS",
    "RECONCILIATION_POLL_SECONDS",
]
