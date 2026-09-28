from datetime import UTC, datetime
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(kind: str) -> str:
    return f"{kind}:{uuid4()}"
