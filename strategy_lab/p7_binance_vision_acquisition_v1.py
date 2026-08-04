#!/usr/bin/env python3
"""Acquire the exact preregistered P7 Binance Vision 5m dataset.

Outcome-blind research data acquisition only. This script downloads the exact
30 immutable monthly archives fixed in the P7 full-recognition preregistration,
validates their candle geometry and timestamps, and emits canonical gzip CSVs
plus a SHA-256 manifest. It does not inspect future outcomes or trade results.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Iterable
from urllib.request import Request, urlopen
from zipfile import ZipFile

RECOGNITION_ID = "SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
MONTHS = tuple(f"2024-{month:02d}" for month in range(1, 7))
START_MS = 1704067200000  # 2024-01-01T00:00:00Z
END_MS = 1719791700000    # 2024-06-30T23:55:00Z
INTERVAL_MS = 5 * 60 * 1000
URL_TEMPLATE = (
    "https://data.binance.vision/data/futures/um/monthly/klines/"
    "{symbol}/5m/{symbol}-5m-{month}.zip"
)


@dataclass(frozen=True)
class ArchiveManifestRow:
    symbol: str
    month: str
    url: str
    archive_filename: str
    csv_filename: str
    size_bytes: int
    sha256: str
    row_count: int
    first_open_time: str
    last_open_time: str


@dataclass(frozen=True)
class CandleRow:
    symbol: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _timestamp_ms(raw: str) -> int:
    value = int(raw)
    if value > 10**15:
        value //= 1000
    elif value > 10**13:
        value //= 1000
    return value


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "SMOKE-CORE-P7-research/1.0"})
    with urlopen(request, timeout=120) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"download failed status={status}: {url}")
        payload = response.read()
    if not payload:
        raise RuntimeError(f"empty archive: {url}")
    return payload


def _parse_archive(symbol: str, month: str, payload: bytes) -> tuple[str, list[CandleRow]]:
    expected_csv = f"{symbol}-5m-{month}.csv"
    with ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if names != [expected_csv]:
            raise ValueError(f"unexpected archive members for {symbol} {month}: {names}")
        with archive.open(expected_csv) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.reader(text)
            output: list[CandleRow] = []
            for index, row in enumerate(reader):
                if not row:
                    continue
                if index == 0 and not row[0].strip().lstrip("-").isdigit():
                    continue
                if len(row) < 6:
                    raise ValueError(f"malformed row {index + 1} in {expected_csv}")
                open_time = _timestamp_ms(row[0])
                candle = CandleRow(
                    symbol=symbol,
                    open_time_ms=open_time,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                if min(candle.open, candle.high, candle.low, candle.close) <= 0:
                    raise ValueError(f"non-positive OHLC at {symbol} {_iso(open_time)}")
                if candle.volume < 0:
                    raise ValueError(f"negative volume at {symbol} {_iso(open_time)}")
                if candle.high < max(candle.open, candle.close):
                    raise ValueError(f"high below body at {symbol} {_iso(open_time)}")
                if candle.low > min(candle.open, candle.close):
                    raise ValueError(f"low above body at {symbol} {_iso(open_time)}")
                output.append(candle)
    if not output:
        raise ValueError(f"no rows in {expected_csv}")
    ordered = sorted(output, key=lambda item: item.open_time_ms)
    if ordered != output:
        raise ValueError(f"archive not chronologically ordered: {expected_csv}")
    timestamps = [item.open_time_ms for item in ordered]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"duplicate timestamps inside {expected_csv}")
    for left, right in zip(timestamps, timestamps[1:]):
        if right - left != INTERVAL_MS:
            raise ValueError(
                f"non-5m cadence inside {expected_csv}: {_iso(left)} -> {_iso(right)}"
            )
    if not all(START_MS <= value <= END_MS for value in timestamps):
        raise ValueError(f"timestamp outside preregistered interval: {expected_csv}")
    return expected_csv, ordered


def _write_symbol(path: Path, rows: Iterable[CandleRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("symbol", "time", "open", "high", "low", "close", "volume"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": row.symbol,
                    "time": _iso(row.open_time_ms),
                    "open": repr(row.open),
                    "high": repr(row.high),
                    "low": repr(row.low),
                    "close": repr(row.close),
                    "volume": repr(row.volume),
                }
            )


def acquire(output_dir: str | Path) -> dict[str, object]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[ArchiveManifestRow] = []
    symbol_rows: dict[str, list[CandleRow]] = {symbol: [] for symbol in SYMBOLS}

    with tempfile.TemporaryDirectory(prefix="smoke-p7-acquisition-"):
        for symbol in SYMBOLS:
            for month in MONTHS:
                url = URL_TEMPLATE.format(symbol=symbol, month=month)
                archive_filename = f"{symbol}-5m-{month}.zip"
                payload = _download(url)
                digest = hashlib.sha256(payload).hexdigest()
                csv_filename, rows = _parse_archive(symbol, month, payload)
                symbol_rows[symbol].extend(rows)
                manifest_rows.append(
                    ArchiveManifestRow(
                        symbol=symbol,
                        month=month,
                        url=url,
                        archive_filename=archive_filename,
                        csv_filename=csv_filename,
                        size_bytes=len(payload),
                        sha256=digest,
                        row_count=len(rows),
                        first_open_time=_iso(rows[0].open_time_ms),
                        last_open_time=_iso(rows[-1].open_time_ms),
                    )
                )

    canonical: dict[str, dict[str, object]] = {}
    for symbol, rows in symbol_rows.items():
        rows.sort(key=lambda item: item.open_time_ms)
        timestamps = [item.open_time_ms for item in rows]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"duplicate timestamps across archives for {symbol}")
        for left, right in zip(timestamps, timestamps[1:]):
            if right - left != INTERVAL_MS:
                raise ValueError(f"cross-archive non-5m cadence for {symbol}: {_iso(left)} -> {_iso(right)}")
        expected_first = START_MS
        expected_last = END_MS
        if timestamps[0] != expected_first or timestamps[-1] != expected_last:
            raise ValueError(
                f"incomplete fixed interval for {symbol}: {_iso(timestamps[0])} .. {_iso(timestamps[-1])}"
            )
        filename = f"{symbol}_5m_2024-01-01_2024-06-30.csv.gz"
        path = root / filename
        _write_symbol(path, rows)
        canonical[symbol] = {
            "filename": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": len(rows),
            "first_open_time": _iso(timestamps[0]),
            "last_open_time": _iso(timestamps[-1]),
        }

    manifest = {
        "recognition_id": RECOGNITION_ID,
        "source": "Binance Vision USD-M Futures monthly klines",
        "interval": "5m",
        "start_inclusive": _iso(START_MS),
        "end_inclusive": _iso(END_MS),
        "symbols": list(SYMBOLS),
        "months": list(MONTHS),
        "archive_count": len(manifest_rows),
        "archives": [asdict(item) for item in manifest_rows],
        "canonical_files": canonical,
    }
    if manifest["archive_count"] != 30:
        raise AssertionError("exactly 30 archives are required")
    manifest_path = root / "p7_full_recognition_data_manifest_v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main() -> int:
    output = Path("research_outputs/p7_full_recognition_data_v1")
    manifest = acquire(output)
    print(json.dumps({
        "recognition_id": manifest["recognition_id"],
        "archive_count": manifest["archive_count"],
        "symbols": manifest["symbols"],
        "status": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
