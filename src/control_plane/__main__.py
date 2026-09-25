from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from .app import create_app
from .config import ControlPlaneConfig
from .telemetry import configure_telemetry


def main() -> None:
    parser = argparse.ArgumentParser(prog="control-plane")
    parser.add_argument("--config", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = ControlPlaneConfig.load(Path(args.config) if args.config else None)
    app = create_app(config)
    configure_telemetry(app)
    uvicorn.run(
        app,
        host=args.host or config.host,
        port=args.port or config.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
