#!/usr/bin/env python3
"""Public Binance market data loader.

Loads public klines and writes project-compatible candles.csv.

Primary source is Binance USDT-M Futures. If that endpoint is geo-blocked
(for example on GitHub-hosted runners), the loader falls back to Binance Vision
public spot klines. This keeps CI research checks usable without API keys.

Research only. No API keys. No private endpoints. No order execution.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


BINANCE_FAPI_BASE_URL = "https://fapi.binance.com"
BINANCE_VISION_SPOT_BASE_URL = "https://data-api.binance.vision"
FUTURES_KLINES_PATH = "/fapi/v1/klines"
SPOT_KLINES_PATH = "/api/v3/klines"


@dataclass(frozen=True)
class CandleRow:
    symbol: str
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketDataSummary:
    symbols_requested: int
    symbols_loaded: int
    candles: int
    interval: str
    status: str


def ms_to_iso(ms: int | float | str) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace("_", "")


def build_klines_url(
    symbol: str,
    interval: str = "1h",
    limit: int = 500,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    source: str = "futures",
) -> str:
    params: dict[str, str | int] = {
        "symbol": normalize_symbol(symbol),
        "interval": interval,
        "limit": max(1, min(int(limit), 1500)),
    }
    if start_time_ms is not None:
        params["startTime"] = int(start_time_ms)
    if end_time_ms is not None:
        params["endTime"] = int(end_time_ms)
    if source == "spot_vision":
        return f"{BINANCE_VISION_SPOT_BASE_URL}{SPOT_KLINES_PATH}?{urllib.parse.urlencode(params)}"
    return f"{BINANCE_FAPI_BASE_URL}{FUTURES_KLINES_PATH}?{urllib.parse.urlencode(params)}"


def default_fetch_json(url: str, timeout: int = 20) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "SmokeStrategyLab/market-data"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - public Binance endpoint only
        return json.loads(response.read().decode("utf-8"))


def parse_kline_rows(symbol: str, payload: object) -> list[CandleRow]:
    if not isinstance(payload, list):
        raise ValueError("Klines payload must be a list")
    out: list[CandleRow] = []
    normalized = normalize_symbol(symbol)
    for item in payload:
        if not isinstance(item, list) or len(item) < 6:
            continue
        out.append(CandleRow(
            symbol=normalized,
            time=ms_to_iso(item[0]),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
        ))
    return out


def fetch_symbol_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 500,
    fetch_json: Callable[[str], object] | None = None,
    source: str = "auto",
) -> list[CandleRow]:
    fetcher = fetch_json or default_fetch_json
    sources = [source]
    if source == "auto":
        sources = ["futures", "spot_vision"]

    last_error: Exception | None = None
    for candidate in sources:
        url = build_klines_url(symbol=symbol, interval=interval, limit=limit, source=candidate)
        try:
            payload = fetcher(url)
            return parse_kline_rows(symbol, payload)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 451 and candidate == "futures" and source == "auto":
                print(f"WARNING: Binance Futures endpoint geo-blocked for {symbol}; trying Binance Vision spot klines.")
                continue
            raise
    if last_error:
        raise last_error
    return []


def write_candles_csv(path: str | Path, rows: Iterable[CandleRow]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_dicts = [asdict(row) for row in rows]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(row_dicts)
    return len(row_dicts)


def load_binance_futures_candles(
    symbols: list[str],
    out_csv: str | Path,
    interval: str = "1h",
    limit: int = 500,
    sleep_sec: float = 0.05,
    fetch_json: Callable[[str], object] | None = None,
    source: str = "auto",
) -> MarketDataSummary:
    rows: list[CandleRow] = []
    loaded = 0
    for symbol in symbols:
        klines = fetch_symbol_klines(symbol=symbol, interval=interval, limit=limit, fetch_json=fetch_json, source=source)
        if klines:
            loaded += 1
            rows.extend(klines)
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    rows = sorted(rows, key=lambda row: (row.symbol, row.time))
    count = write_candles_csv(out_csv, rows)
    return MarketDataSummary(
        symbols_requested=len(symbols),
        symbols_loaded=loaded,
        candles=count,
        interval=interval,
        status="OK" if count > 0 else "EMPTY",
    )


def parse_symbols(value: str) -> list[str]:
    return [normalize_symbol(part) for part in value.replace("\n", ",").split(",") if part.strip()]
