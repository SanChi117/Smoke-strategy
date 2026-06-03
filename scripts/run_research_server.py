#!/usr/bin/env python3
"""Run Smoke Strategy research API server."""

from __future__ import annotations

import argparse

from strategy_lab.research_server import run_server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--base-dir", default=".")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, base_dir=args.base_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
