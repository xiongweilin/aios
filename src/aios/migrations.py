from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _absolute_path(name: str) -> Path:
    path = Path(_required(name)).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    return path.resolve()


def upgrade(component: str) -> None:
    if component == "administrative":
        database_url = _required("ADMIN_DATABASE_URL")
        script_location = _absolute_path("ADMIN_ALEMBIC_SCRIPT_LOCATION")
    elif component == "autonomous-development":
        database_url = _required("AUTODEV_DATABASE_URL")
        script_location = _absolute_path("AUTODEV_ALEMBIC_SCRIPT_LOCATION")
    else:
        raise RuntimeError(f"unknown migration component: {component}")

    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def main() -> None:
    component = _required("AIOS_MIGRATION_COMPONENT")
    upgrade(component)


if __name__ == "__main__":
    main()
