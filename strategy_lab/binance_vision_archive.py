#!/usr/bin/env python3
"""Merge official Binance Vision USD-M Futures kline archives.

The input is a directory produced by Binance's public-data downloader with
``-t um`` (USD-M futures). Monthly and daily ZIP files can overlap; rows are
therefore deduplicated by ``symbol + open_time`` before writing the project
candle CSV.

Research only. Public market data. No API keys. No order execution.
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ARCHIVE_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)-(?P<interval>[0-9]+[smhdwM])-(?P<period>[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?)\.zip$"
)


@dataclass(frozen=True)
class ArchiveMergeSummary:
    source: str
    input_dir: str
    interval: str
    start_date: str
    end_date: str
    archives_scanned: int
    archives_used: int
    csv_members_read: int
    malformed_rows: int
    duplicate_rows: int
    symbols_requested: int
    symbols_loaded: int
    missing_symbols: tuple[str, ...]
    rows_written: int
    first_candle: str
    last_candle: str
    coverage_pct: float
    status: str


def parse_symbols(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in re.split(r"[\s,;]+", str(value)):
            symbol = token.strip().upper().replace("/", "").replace("_", "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            out.append(symbol)
    return out


def read_symbols_file(path: str | Path) -> list[str]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Symbols file not found: {target}")
    return parse_symbols([target.read_text(encoding="utf-8")])


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def interval_delta(interval: str) -> timedelta:
    match = re.fullmatch(r"([0-9]+)([smhdwM])", interval)
    if not match:
        raise ValueError(f"Unsupported interval: {interval}")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ValueError(f"Invalid interval: {interval}")
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)
    # Binance's capital-M interval is one calendar month. It is not used by SMOKE,
    # but using 31 days here keeps the close-time safety check conservative.
    return timedelta(days=31 * amount)


def normalize_epoch_ms(value: str | int | float) -> int:
    """Normalize seconds/milliseconds/microseconds/nanoseconds to milliseconds."""

    raw = int(float(str(value).strip()))
    if raw <= 0:
        raise ValueError("timestamp must be positive")
    while raw >= 10**15:
        raw //= 1000
    if raw < 10**11:
        raw *= 1000
    if not 10**11 <= raw < 10**14:
        raise ValueError(f"timestamp outside expected epoch range: {value}")
    return raw


def epoch_ms_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def archive_identity(path: Path) -> tuple[str, str] | None:
    match = ARCHIVE_RE.match(path.name)
    if not match:
        return None
    return match.group("symbol"), match.group("interval")


def numeric_row(row: list[str]) -> bool:
    if len(row) < 6:
        return False
    try:
        normalize_epoch_ms(row[0])
        for value in row[1:6]:
            float(value)
    except (TypeError, ValueError):
        return False
    return True


def merge_archives(
    input_dir: str | Path,
    out_csv: str | Path,
    symbols: Iterable[str],
    interval: str,
    start_date: str | date,
    end_date: str | date,
    summary_json: str | Path | None = None,
    min_coverage: float = 0.75,
    now: datetime | None = None,
) -> ArchiveMergeSummary:
    """Merge archive ZIPs into ``symbol,time,open,high,low,close,volume`` CSV.

    ``end_date`` is inclusive. A row is accepted only when the whole candle has
    closed by both the inclusive date boundary and ``now``.
    """

    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Archive directory not found: {root}")
    requested = parse_symbols(symbols)
    if not requested:
        raise ValueError("No symbols requested")
    requested_set = set(requested)
    start_day = parse_date(start_date)
    end_day = parse_date(end_date)
    if end_day < start_day:
        raise ValueError("end_date must not be earlier than start_date")
    start_dt = datetime.combine(start_day, datetime.min.time())
    end_exclusive = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
    current = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    candle_delta = interval_delta(interval)

    archives = sorted(root.rglob("*.zip"))
    archives_used = 0
    csv_members_read = 0
    malformed_rows = 0
    duplicate_rows = 0
    # Compact tuple payload: open, high, low, close, volume.
    candles: dict[tuple[str, int], tuple[float, float, float, float, float]] = {}

    for archive in archives:
        identity = archive_identity(archive)
        if identity is None:
            continue
        symbol, archive_interval = identity
        if symbol not in requested_set or archive_interval != interval:
            continue
        archive_contributed = False
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = sorted(name for name in bundle.namelist() if name.lower().endswith(".csv"))
                for member in members:
                    csv_members_read += 1
                    with bundle.open(member) as raw:
                        text = (line.decode("utf-8-sig", errors="replace") for line in raw)
                        reader = csv.reader(text)
                        for row in reader:
                            if not row or not numeric_row(row):
                                # Official files can include a header. Count only rows
                                # that look like data but are malformed; plain headers
                                # are skipped without penalising the archive.
                                if row and str(row[0]).strip().lower() not in {
                                    "open_time", "opentime", "timestamp", "time"
                                }:
                                    malformed_rows += 1
                                continue
                            try:
                                open_ms = normalize_epoch_ms(row[0])
                                open_dt = epoch_ms_to_datetime(open_ms)
                                if open_dt < start_dt or open_dt >= end_exclusive:
                                    continue
                                if open_dt + candle_delta > current or open_dt + candle_delta > end_exclusive:
                                    continue
                                payload = tuple(float(value) for value in row[1:6])
                                if payload[0] <= 0 or payload[1] <= 0 or payload[2] <= 0 or payload[3] <= 0 or payload[4] < 0:
                                    malformed_rows += 1
                                    continue
                                if payload[1] < max(payload[0], payload[3]) or payload[2] > min(payload[0], payload[3]):
                                    malformed_rows += 1
                                    continue
                            except (TypeError, ValueError, OverflowError):
                                malformed_rows += 1
                                continue
                            key = (symbol, open_ms)
                            if key in candles:
                                duplicate_rows += 1
                            candles[key] = payload  # daily archive may replace identical monthly row
                            archive_contributed = True
        except (OSError, zipfile.BadZipFile):
            malformed_rows += 1
            continue
        if archive_contributed:
            archives_used += 1

    loaded_symbols = sorted({symbol for symbol, _timestamp in candles})
    missing_symbols = tuple(sorted(requested_set - set(loaded_symbols)))
    coverage = len(loaded_symbols) / len(requested) if requested else 0.0
    rows_sorted = sorted(candles.items(), key=lambda item: (item[0][0], item[0][1]))
    output = Path(out_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "time", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        for (symbol, open_ms), payload in rows_sorted:
            writer.writerow({
                "symbol": symbol,
                "time": epoch_ms_to_datetime(open_ms).isoformat(timespec="seconds"),
                "open": payload[0],
                "high": payload[1],
                "low": payload[2],
                "close": payload[3],
                "volume": payload[4],
            })

    first = epoch_ms_to_datetime(min((key[1] for key in candles), default=0)).isoformat(timespec="seconds") if candles else ""
    last = epoch_ms_to_datetime(max((key[1] for key in candles), default=0)).isoformat(timespec="seconds") if candles else ""
    status = "OK" if candles and coverage >= min_coverage else "INSUFFICIENT_COVERAGE"
    summary = ArchiveMergeSummary(
        source="BINANCE_VISION_USDM_FUTURES_ARCHIVE",
        input_dir=str(root),
        interval=interval,
        start_date=start_day.isoformat(),
        end_date=end_day.isoformat(),
        archives_scanned=len(archives),
        archives_used=archives_used,
        csv_members_read=csv_members_read,
        malformed_rows=malformed_rows,
        duplicate_rows=duplicate_rows,
        symbols_requested=len(requested),
        symbols_loaded=len(loaded_symbols),
        missing_symbols=missing_symbols,
        rows_written=len(rows_sorted),
        first_candle=first,
        last_candle=last,
        coverage_pct=round(coverage * 100.0, 4),
        status=status,
    )
    if summary_json is not None:
        summary_path = Path(summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if status != "OK":
        raise RuntimeError(
            f"Binance Vision USD-M Futures coverage insufficient: "
            f"{len(loaded_symbols)}/{len(requested)} symbols, rows={len(rows_sorted)}"
        )
    return summary
