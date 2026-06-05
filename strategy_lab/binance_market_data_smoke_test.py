#!/usr/bin/env python3
"""Smoke test for Binance public market data loader using mocked payloads."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from strategy_lab.binance_market_data import build_klines_url, load_binance_futures_candles, parse_symbols


def mock_fetch_json(url: str) -> object:
    query = parse_qs(urlparse(url).query)
    symbol = query["symbol"][0]
    base = 100.0 if symbol == "BTCUSDT" else 10.0
    return [
        [1735689600000, str(base), str(base + 2), str(base - 1), str(base + 1), "1000", 0, 0, 0, 0, 0, 0],
        [1735693200000, str(base + 1), str(base + 3), str(base), str(base + 2), "1200", 0, 0, 0, 0, 0, 0],
    ]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    url = build_klines_url("btc_usdt", interval="15m", limit=2000)
    assert "symbol=BTCUSDT" in url, url
    assert "interval=15m" in url, url
    assert "limit=1500" in url, url
    assert parse_symbols("btc_usdt, ETH/USDT\nsolusdt") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "candles.csv"
        summary = load_binance_futures_candles(
            symbols=["BTCUSDT", "ETHUSDT"],
            out_csv=out,
            interval="1h",
            limit=2,
            sleep_sec=0,
            fetch_json=mock_fetch_json,
        )
        assert summary.status == "OK", summary
        assert summary.symbols_requested == 2, summary
        assert summary.symbols_loaded == 2, summary
        assert summary.candles == 4, summary
        rows = read_rows(out)
        assert len(rows) == 4, rows
        assert rows[0]["symbol"] == "BTCUSDT", rows
        assert rows[0]["time"] == "2025-01-01T00:00:00", rows
        assert rows[0]["open"] == "100.0", rows
        assert rows[-1]["symbol"] == "ETHUSDT", rows
    print("BINANCE MARKET DATA SMOKE TEST OK")


if __name__ == "__main__":
    main()
