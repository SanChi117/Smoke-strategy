#!/usr/bin/env python3
"""Exchange-neutral OHLCV CSV adapter.

Normalizes common external candle CSV formats into the internal format:

symbol,time,open,high,low,close,volume

Research only. No exchange calls. No API keys. No live trading.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TIME_COLUMNS = ["time", "timestamp", "datetime", "date", "open_time", "opentime"]
SYMBOL_COLUMNS = ["symbol", "pair", "ticker", "market"]
OPEN_COLUMNS = ["open", "o"]
HIGH_COLUMNS = ["high", "h"]
LOW_COLUMNS = ["low", "l"]
CLOSE_COLUMNS = ["close", "c"]
VOLUME_COLUMNS = ["volume", "vol", "base_volume", "v"]


@dataclass(frozen=True)
class AdapterIssue:
    level: str
    row_number: int
    check: str
    message: str


@dataclass(frozen=True)
class AdapterSummary:
    input_rows: int
    output_rows: int
    skipped_rows: int
    issues: int
    status: str


def norm_name(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def find_col(fieldnames: list[str], candidates: list[str]) -> str | None:
    normalized = {norm_name(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def parse_time(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("empty time")
    # Numeric timestamps: seconds or milliseconds.
    if text.replace(".", "", 1).isdigit():
        raw = float(text)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    return datetime.fromisoformat(text.replace("Z", "")).isoformat(timespec="seconds")


def normalize_symbol(value: str, default_quote: str = "USDT") -> str:
    symbol = str(value).strip().upper().replace("/", "").replace("-", "").replace("_", "")
    if not symbol:
        raise ValueError("empty symbol")
    if default_quote and not symbol.endswith(default_quote.upper()):
        symbol = f"{symbol}{default_quote.upper()}"
    return symbol


def write_dict_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]


def adapt_ohlcv_csv(
    input_csv: str | Path,
    output_csv: str | Path,
    report_dir: str | Path,
    default_symbol: str | None = None,
    default_quote: str = "USDT",
) -> AdapterSummary:
    input_csv = Path(input_csv)
    output_csv = Path(output_csv)
    report_dir = Path(report_dir)
    output_rows: list[dict] = []
    issues: list[AdapterIssue] = []

    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if not fields:
            raise ValueError("Input CSV has no header")
        time_col = find_col(fields, TIME_COLUMNS)
        symbol_col = find_col(fields, SYMBOL_COLUMNS)
        open_col = find_col(fields, OPEN_COLUMNS)
        high_col = find_col(fields, HIGH_COLUMNS)
        low_col = find_col(fields, LOW_COLUMNS)
        close_col = find_col(fields, CLOSE_COLUMNS)
        volume_col = find_col(fields, VOLUME_COLUMNS)
        missing = []
        for name, col in [("time", time_col), ("open", open_col), ("high", high_col), ("low", low_col), ("close", close_col), ("volume", volume_col)]:
            if not col:
                missing.append(name)
        if not symbol_col and not default_symbol:
            missing.append("symbol")
        if missing:
            raise ValueError(f"Missing required source columns: {missing}")

        input_rows = 0
        for row_number, row in enumerate(reader, start=2):
            input_rows += 1
            try:
                symbol_value = row.get(symbol_col, "") if symbol_col else str(default_symbol)
                out = {
                    "symbol": normalize_symbol(symbol_value, default_quote=default_quote),
                    "time": parse_time(str(row.get(time_col, ""))),
                    "open": float(row.get(open_col, "")),
                    "high": float(row.get(high_col, "")),
                    "low": float(row.get(low_col, "")),
                    "close": float(row.get(close_col, "")),
                    "volume": float(row.get(volume_col, "")),
                }
                output_rows.append(out)
            except Exception as exc:
                issues.append(AdapterIssue("warning", row_number, "row_parse", str(exc)))

    output_rows = sorted(output_rows, key=lambda r: (r["symbol"], r["time"]))
    write_dict_csv(output_csv, output_rows)
    summary = AdapterSummary(
        input_rows=input_rows,
        output_rows=len(output_rows),
        skipped_rows=input_rows - len(output_rows),
        issues=len(issues),
        status="WARN" if issues else "OK",
    )
    write_dict_csv(report_dir / "market_data_adapter_summary.csv", rows_as_dicts([summary]))
    write_dict_csv(report_dir / "market_data_adapter_issues.csv", rows_as_dicts(issues))
    return summary
