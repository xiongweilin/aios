from __future__ import annotations

import os

import psycopg
from psycopg import sql


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    dsn = _required("AIOS_POSTGRES_ADMIN_DSN")
    names = [name.strip() for name in _required("AIOS_POSTGRES_DATABASES").split(",")]
    names = [name for name in names if name]
    if not names:
        raise RuntimeError("AIOS_POSTGRES_DATABASES must contain at least one database")

    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for name in names:
                cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
                if cursor.fetchone() is not None:
                    continue
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


if __name__ == "__main__":
    main()
