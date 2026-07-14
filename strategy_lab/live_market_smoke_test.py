#!/usr/bin/env python3
"""Smoke tests for closed-candle filtering and incremental storage."""

from __future__ import annotations

import tempfile
from pathlib import Path

from strategy_lab.live_market import CandleStore, parse_closed_klines, sync_symbol


def kline(open_ms: int, close_ms: int, close: float) -> list[object]:
    return [open_ms, "10", "11", "9", str(close), "100", close_ms, "0", 0, "0", "0", "0"]


def main() -> None:
    now_ms = 2_000_000
    payload = [
        kline(0, 899_999, 10.5),
        kline(900_000, 1_799_999, 10.7),
        kline(1_800_000, 2_699_999, 10.9),
    ]
    rows = parse_closed_klines("BTCUSDT", "15m", payload, now_ms=now_ms)
    assert len(rows) == 2
    assert rows[-1].close == 10.7

    with tempfile.TemporaryDirectory() as td:
        store = CandleStore(Path(td) / "live.sqlite3")
        result = sync_symbol(store, "BTCUSDT", "15m", bootstrap_limit=100, fetcher=lambda _url: payload, now_ms=now_ms)
        assert result.stored == 2
        assert len(store.candles("BTCUSDT", "15m")) == 2

        next_payload = [kline(1_800_000, 2_699_999, 11.1)]
        result2 = sync_symbol(store, "BTCUSDT", "15m", fetcher=lambda _url: next_payload, now_ms=3_000_000)
        assert result2.requested_from_ms == 1_800_000
        assert len(store.candles("BTCUSDT", "15m")) == 3
    print("LIVE MARKET SMOKE TEST OK")


if __name__ == "__main__":
    main()
