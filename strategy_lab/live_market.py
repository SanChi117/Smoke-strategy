#!/usr/bin/env python3
"""Incremental public Binance Futures candle storage for SMOKE paper mode.

Only closed candles are persisted. The live scanner downloads a bootstrap once,
then requests only candles newer than the latest stored bar.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from strategy_lab.market_data import Candle


FAPI_BASE = "https://fapi.binance.com"
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


@dataclass(frozen=True)
class ClosedCandleRow:
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_candle(self) -> Candle:
        ts = datetime.fromtimestamp(self.open_time_ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        return Candle(self.symbol, ts, self.open, self.high, self.low, self.close, self.volume)


@dataclass(frozen=True)
class SyncResult:
    symbol: str
    interval: str
    requested_from_ms: int | None
    received: int
    stored: int
    latest_open_time_ms: int | None


def normalize_symbol(value: str) -> str:
    return str(value).strip().upper().replace("/", "").replace("_", "")


def fetch_json(url: str, timeout: int = 20) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "SmokeStrategy/live-market"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - public Binance endpoint
        return json.loads(response.read().decode("utf-8"))


def build_klines_url(symbol: str, interval: str, limit: int, start_time_ms: int | None = None) -> str:
    params: dict[str, Any] = {
        "symbol": normalize_symbol(symbol),
        "interval": interval,
        "limit": max(1, min(int(limit), 1500)),
    }
    if start_time_ms is not None:
        params["startTime"] = int(start_time_ms)
    return f"{FAPI_BASE}/fapi/v1/klines?{urllib.parse.urlencode(params)}"


def parse_closed_klines(symbol: str, interval: str, payload: Any, *, now_ms: int | None = None) -> list[ClosedCandleRow]:
    """Parse Binance rows and reject the currently forming candle."""
    if not isinstance(payload, list):
        raise ValueError("Binance kline payload must be a list")
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    out: list[ClosedCandleRow] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 7:
            continue
        open_ms = int(item[0])
        close_ms = int(item[6])
        if close_ms >= now_ms:
            continue
        out.append(
            ClosedCandleRow(
                symbol=normalize_symbol(symbol),
                interval=interval,
                open_time_ms=open_ms,
                close_time_ms=close_ms,
                open=float(item[1]),
                high=float(item[2]),
                low=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
            )
        )
    return sorted(out, key=lambda row: row.open_time_ms)


class CandleStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_candles (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    close_time_ms INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY(symbol, interval, open_time_ms)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_candles_latest ON market_candles(symbol, interval, open_time_ms DESC)")
            conn.commit()

    def upsert(self, rows: Iterable[ClosedCandleRow]) -> int:
        values = [
            (row.symbol, row.interval, row.open_time_ms, row.close_time_ms, row.open, row.high, row.low, row.close, row.volume)
            for row in rows
        ]
        if not values:
            return 0
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT INTO market_candles(symbol, interval, open_time_ms, close_time_ms, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time_ms) DO UPDATE SET
                    close_time_ms=excluded.close_time_ms,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                values,
            )
            conn.commit()
            return conn.total_changes - before

    def latest_open_time_ms(self, symbol: str, interval: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(open_time_ms) AS value FROM market_candles WHERE symbol=? AND interval=?",
                (normalize_symbol(symbol), interval),
            ).fetchone()
        return int(row["value"]) if row and row["value"] is not None else None

    def candles(self, symbol: str, interval: str, limit: int = 1500) -> list[Candle]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, interval, open_time_ms, close_time_ms, open, high, low, close, volume
                FROM market_candles
                WHERE symbol=? AND interval=?
                ORDER BY open_time_ms DESC
                LIMIT ?
                """,
                (normalize_symbol(symbol), interval, int(limit)),
            ).fetchall()
        return [
            ClosedCandleRow(
                row["symbol"], row["interval"], int(row["open_time_ms"]), int(row["close_time_ms"]),
                float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"]),
            ).as_candle()
            for row in reversed(rows)
        ]

    def all_candles(self, symbols: Iterable[str], interval: str, limit_per_symbol: int = 1500) -> list[Candle]:
        out: list[Candle] = []
        for symbol in symbols:
            out.extend(self.candles(symbol, interval, limit_per_symbol))
        return out


def sync_symbol(
    store: CandleStore,
    symbol: str,
    interval: str = "15m",
    bootstrap_limit: int = 1200,
    fetcher: Callable[[str], Any] | None = None,
    now_ms: int | None = None,
) -> SyncResult:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")
    latest = store.latest_open_time_ms(symbol, interval)
    start = latest + INTERVAL_MS[interval] if latest is not None else None
    limit = 1500 if start is not None else bootstrap_limit
    payload = (fetcher or fetch_json)(build_klines_url(symbol, interval, limit, start))
    rows = parse_closed_klines(symbol, interval, payload, now_ms=now_ms)
    stored = store.upsert(rows)
    return SyncResult(
        symbol=normalize_symbol(symbol),
        interval=interval,
        requested_from_ms=start,
        received=len(payload) if isinstance(payload, list) else 0,
        stored=stored,
        latest_open_time_ms=store.latest_open_time_ms(symbol, interval),
    )


def fetch_active_usdt_perpetual_symbols(fetcher: Callable[[str], Any] | None = None) -> set[str]:
    payload = (fetcher or fetch_json)(f"{FAPI_BASE}/fapi/v1/exchangeInfo")
    symbols = set()
    for item in payload.get("symbols", []) if isinstance(payload, dict) else []:
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("contractType") != "PERPETUAL":
            continue
        symbols.add(normalize_symbol(item.get("symbol", "")))
    return symbols


def validate_universe(symbols: Iterable[str], active_symbols: set[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if symbol and symbol in active_symbols and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out
