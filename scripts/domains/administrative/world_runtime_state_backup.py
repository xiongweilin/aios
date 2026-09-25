from __future__ import annotations

import argparse
from pathlib import Path

from administrative_orchestrator.world_runtime_state_dr import (
    WorldRuntimeStateRecoveryError,
    backup_world_runtime_state,
    restore_world_runtime_state,
    verify_world_runtime_state_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Online backup, integrity verification, and restore for production "
            "World Runtime SQLite state."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("backup", type=Path)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("destination", type=Path)
    restore_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "backup":
            args.destination.parent.mkdir(parents=True, exist_ok=True)
            digest = backup_world_runtime_state(args.source, args.destination)
            print(f"World Runtime state backup ready sha256={digest}")
        elif args.command == "verify":
            digest = verify_world_runtime_state_backup(args.backup)
            print(f"World Runtime state backup verified sha256={digest}")
        else:
            args.destination.parent.mkdir(parents=True, exist_ok=True)
            digest = restore_world_runtime_state(
                args.backup,
                args.destination,
                force=args.force,
            )
            print(f"World Runtime state restored from verified backup sha256={digest}")
    except WorldRuntimeStateRecoveryError as exc:
        raise SystemExit(f"World Runtime state DR failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
