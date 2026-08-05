#!/usr/bin/env python3
"""SMOKE Terminal V3: Binance-style interactive paper/research dashboard.

V3 is an isolated presentation and chart-transport layer on top of the hardened
V2 paper server. It does not alter candidate generation, decisions, risk rules,
trade lifecycle or exchange execution. Real orders remain impossible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import smoke_control_server as core  # noqa: E402
from scripts import smoke_control_server_v2 as hardening  # noqa: E402
from strategy_lab.terminal_chart_data import (  # noqa: E402
    SUPPORTED_TIMEFRAMES,
    aggregate_ohlcv,
    chart_bundle,
    latest_market_stats,
)

TERMINAL_HTML = ROOT / "web" / "smoke_terminal_v3.html"
BASE_SECONDS = 15 * 60


def _int_arg(values: dict[str, list[str]], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(values.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _symbol(value: str) -> str:
    return value.strip().upper().replace("/", "").replace("_", "")


def chart_payload(symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
    symbol = _symbol(symbol)
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    with core.STATE_LOCK:
        universe = list(core.STATE.get("universe") or [])
    if universe and symbol not in universe:
        raise ValueError(f"symbol is outside active universe: {symbol}")

    factor = max(1, SUPPORTED_TIMEFRAMES[timeframe] // BASE_SECONDS)
    raw_limit = min(10000, max(300, limit * factor + 250))
    raw = core.STORE.candles(symbol, core.SETTINGS.interval, raw_limit)
    bundle = chart_bundle(raw, timeframe, limit)
    candidates = core.query_rows(
        "SELECT * FROM candidates WHERE symbol=? ORDER BY entry_time DESC LIMIT 300",
        (symbol,),
    )
    trades = core.query_rows(
        "SELECT * FROM paper_trades WHERE symbol=? ORDER BY entry_time DESC LIMIT 300",
        (symbol,),
    )
    bundle.update(
        {
            "ok": True,
            "symbol": symbol,
            "base_interval": core.SETTINGS.interval,
            "candidates": candidates,
            "trades": trades,
            "status": core.status_payload(),
            "server_time_utc": core.iso_now(),
        }
    )
    return bundle


def market_overview() -> dict[str, Any]:
    with core.STATE_LOCK:
        universe = list(core.STATE.get("universe") or [])
    ready_rows = core.query_rows(
        "SELECT symbol, COUNT(*) AS n FROM candidates WHERE final_status='READY' GROUP BY symbol"
    )
    open_rows = core.query_rows(
        "SELECT symbol, COUNT(*) AS n FROM paper_trades WHERE status='open' GROUP BY symbol"
    )
    ready = {str(row["symbol"]): int(row["n"]) for row in ready_rows}
    opened = {str(row["symbol"]): int(row["n"]) for row in open_rows}
    items: list[dict[str, Any]] = []
    for symbol in universe:
        raw = core.STORE.candles(symbol, core.SETTINGS.interval, 96)
        rows = aggregate_ohlcv(raw, "15m")
        stats = latest_market_stats(rows)
        items.append(
            {
                "symbol": symbol,
                **stats,
                "ready": ready.get(symbol, 0),
                "open_trades": opened.get(symbol, 0),
            }
        )
    return {"ok": True, "items": items, "time_utc": core.iso_now()}


class TerminalHandler(core.Handler):
    server_version = "SmokeTerminal/3.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            super().do_GET()
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return

        if parsed.path == "/":
            if not TERMINAL_HTML.is_file():
                self._send(500, {"ok": False, "error": "terminal_html_missing"})
                return
            self._send(200, TERMINAL_HTML.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/legacy":
            self._send(200, core.DASHBOARD_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/terminal-capabilities":
            self._send(
                200,
                {
                    "ok": True,
                    "timeframes": list(SUPPORTED_TIMEFRAMES),
                    "base_interval": core.SETTINGS.interval,
                    "features": [
                        "candles",
                        "volume",
                        "ema20",
                        "ema50",
                        "ema200",
                        "crosshair",
                        "zoom_pan",
                        "setup_markers",
                        "entry_stop_target",
                        "measurement",
                        "fullscreen",
                        "persistent_layout",
                    ],
                    "mode": "paper_only_no_orders",
                },
            )
            return
        if parsed.path == "/api/market-overview":
            self._send(200, market_overview())
            return
        if parsed.path == "/api/chart":
            values = parse_qs(parsed.query)
            with core.STATE_LOCK:
                universe = list(core.STATE.get("universe") or [])
            default_symbol = universe[0] if universe else core.SETTINGS.requested_symbols()[0]
            symbol = values.get("symbol", [default_symbol])[0]
            timeframe = values.get("timeframe", ["15m"])[0]
            limit = _int_arg(values, "limit", 1200, 100, 5000)
            try:
                self._send(200, chart_payload(symbol, timeframe, limit))
            except ValueError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            return
        super().do_GET()


def main() -> int:
    hardening.apply_patches()
    core.Handler = TerminalHandler
    core.log_event = core.log_event
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
