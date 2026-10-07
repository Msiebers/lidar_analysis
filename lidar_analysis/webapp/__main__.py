"""Run the local experiment configuration editor:

    python -m lidar_analysis.webapp [--port 8000]

Always binds to 127.0.0.1 -- there is deliberately no option to listen on
another interface. From another computer, reach it through an SSH tunnel
(the startup message prints the exact command).
"""
from __future__ import annotations

import argparse

import uvicorn

from lidar_analysis.webapp.app import create_app

HOST = "127.0.0.1"


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a port number: {text!r}") from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535, got {value}")
    return value


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m lidar_analysis.webapp",
        description="Local browser-based editor for experiment_config.yaml (listens on 127.0.0.1 only).",
    )
    parser.add_argument("--port", type=_port, default=8000, help="port on 127.0.0.1 (default: 8000)")
    args = parser.parse_args(argv)

    print(f"Experiment configuration editor: http://{HOST}:{args.port}")
    print("Listening on this computer only. To use it from another computer, run there:")
    print(f"    ssh -L {args.port}:{HOST}:{args.port} <user>@<this-machine>")
    print(f"and open http://{HOST}:{args.port} in that computer's browser. Stop with Ctrl-C.", flush=True)
    uvicorn.run(create_app(), host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
