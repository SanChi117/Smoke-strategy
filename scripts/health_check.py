#!/usr/bin/env python3
"""Health-check Smoke Strategy research server."""

from __future__ import annotations

import argparse
import json
from http.client import HTTPConnection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args()

    conn = HTTPConnection(args.host, args.port, timeout=args.timeout)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        payload = json.loads(data)
        if resp.status != 200 or payload.get("status") != "ok" or payload.get("mode") != "research":
            print(f"UNHEALTHY status={resp.status} payload={payload}")
            return 1
        print(f"OK {payload}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
