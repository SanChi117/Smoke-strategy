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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable


BINANCE_FAPI_BASE_URL = "https://fapi.binance.com"
BINANCE_VISION_SPOT_BASE_URL = "https://data-api.binance.vision"
FUTURES_KLINES_PATH = "/fapi/v1/klines"
SPOT_KLINES_PATH = "/api/v3/klines"
FUTURES_MAX_LIMIT = 1500
SPOT_MAX_LIMIT = 1000
STALE_SYMBOL_MAX_LAG_DAYS = 7


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


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace("_", "")


def source_max_limit(source: str) -> int:
    return SPOT_MAX_LIMIT if source == "spot_vision" else FUTURES_MAX_LIMIT


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
        "limit": max(1, min(int(limit), source_max_limit(source))),
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


def fetch_symbol_klines_single(
    symbol: str,
    interval: str,
    limit: int,
    fetcher: Callable[[str], object],
    source: str,
    end_time_ms: int | None = None,
) -> list[CandleRow]:
    url = build_klines_url(symbol=symbol, interval=interval, limit=limit, end_time_ms=end_time_ms, source=source)
    payload = fetcher(url)
    return parse_kline_rows(symbol, payload)


def fetch_symbol_klines_paged(
    symbol: str,
    interval: str,
    limit: int,
    fetcher: Callable[[str], object],
    source: str,
) -> list[CandleRow]:
    """Fetch up to `limit` candles, paging backwards when one request is not enough."""
    requested = max(1, int(limit))
    max_batch = source_max_limit(source)
    rows: list[CandleRow] = []
    seen: set[tuple[str, str]] = set()
    end_time_ms: int | None = None

    while len(rows) < requested:
        batch_limit = min(max_batch, requested - len(rows))
        batch = fetch_symbol_klines_single(
            symbol=symbol,
            interval=interval,
            limit=batch_limit,
            fetcher=fetcher,
            source=source,
            end_time_ms=end_time_ms,
        )
        if not batch:
            break

        new_rows: list[CandleRow] = []
        for row in batch:
            key = (row.symbol, row.time)
            if key not in seen:
                seen.add(key)
                new_rows.append(row)
        if not new_rows:
            break
        rows.extend(new_rows)

        oldest_ms = int(datetime.fromisoformat(min(row.time for row in batch)).replace(tzinfo=timezone.utc).timestamp() * 1000)
        next_end = oldest_ms - 1
        if end_time_ms is not None and next_end >= end_time_ms:
            break
        end_time_ms = next_end
        if len(batch) < batch_limit:
            break

    return sorted(rows, key=lambda row: row.time)[-requested:]


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
        try:
            return fetch_symbol_klines_paged(symbol=symbol, interval=interval, limit=limit, fetcher=fetcher, source=candidate)
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


def filter_stale_symbols(rows: list[CandleRow], max_lag_days: int = STALE_SYMBOL_MAX_LAG_DAYS) -> tuple[list[CandleRow], set[str]]:
    """Drop symbols whose newest candle is far behind the dataset newest candle."""
    if not rows:
        return [], set()
    global_latest = max(parse_iso(row.time) for row in rows)
    cutoff = global_latest - timedelta(days=max_lag_days)
    latest_by_symbol: dict[str, datetime] = {}
    for row in rows:
        ts = parse_iso(row.time)
        latest_by_symbol[row.symbol] = max(ts, latest_by_symbol.get(row.symbol, ts))
    stale = {symbol for symbol, latest in latest_by_symbol.items() if latest < cutoff}
    for symbol in sorted(stale):
        print(
            f"WARNING: Skipping stale symbol {symbol}; latest candle {latest_by_symbol[symbol].isoformat()} "
            f"is older than cutoff {cutoff.isoformat()}."
        )
    return [row for row in rows if row.symbol not in stale], stale


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
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        try:
            klines = fetch_symbol_klines(symbol=normalized, interval=interval, limit=limit, fetch_json=fetch_json, source=source)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"WARNING: Skipping {normalized}; public kline load failed: {exc}")
            klines = []
        if klines:
            rows.extend(klines)
        else:
            print(f"WARNING: No candles loaded for {normalized}; symbol skipped.")
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    rows, _stale_symbols = filter_stale_symbols(rows)
    rows = sorted(rows, key=lambda row: (row.symbol, row.time))
    loaded_symbols = {row.symbol for row in rows}
    count = write_candles_csv(out_csv, rows)
    status = "OK" if count > 0 else "EMPTY"
    return MarketDataSummary(
        symbols_requested=len(symbols),
        symbols_loaded=len(loaded_symbols),
        candles=count,
        interval=interval,
        status=status,
    )


def parse_symbols(value: str) -> list[str]:
    return [normalize_symbol(part) for part in value.replace("\n", ",").split(",") if part.strip()]
