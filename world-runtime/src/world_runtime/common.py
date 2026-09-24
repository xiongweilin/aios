from datetime import datetime, timezone
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(kind: str) -> str:
    return f"{kind}:{uuid4()}"
