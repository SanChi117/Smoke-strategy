#!/usr/bin/env python3
"""Universe input validation and candle filtering.

Allows the user to provide a broad symbol list while the research system checks
which symbols actually exist in the candle dataset and which are usable.

Research only. No live trading. No exchange calls.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from strategy_lab.market_data import Candle, group_candles_by_symbol, read_candles_csv, write_candles_csv


@dataclass(frozen=True)
class UniverseInputConfig:
    min_candles_per_symbol: int = 100


@dataclass(frozen=True)
class UniverseSymbolRow:
    symbol: str
    requested: bool
    candles_available: int
    status: str
    reason: str


@dataclass(frozen=True)
class UniverseInputSummary:
    requested_symbols: int
    candle_symbols: int
    usable_symbols: int
    missing_symbols: int
    under_min_history_symbols: int
    filtered_candles: int
    status: str


def normalize_symbol(value: str) -> str:
    return str(value).strip().upper()


def read_universe_symbols(path: str | Path) -> list[str]:
    path = Path(path)
    symbols: list[str] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        sample = f.read(2048)
        f.seek(0)
        if "," in sample or "symbol" in sample.lower():
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            column = "symbol" if "symbol" in fieldnames else fieldnames[0] if fieldnames else ""
            if not column:
                return []
            for row in reader:
                symbol = normalize_symbol(row.get(column, ""))
                if symbol:
                    symbols.append(symbol)
        else:
            for line in f:
                symbol = normalize_symbol(line)
                if symbol:
                    symbols.append(symbol)
    # Preserve order while removing duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def analyze_universe_input(candles: Iterable[Candle], requested_symbols: Iterable[str], cfg: UniverseInputConfig | None = None) -> tuple[UniverseInputSummary, list[UniverseSymbolRow], list[Candle]]:
    cfg = cfg or UniverseInputConfig()
    candle_rows = list(candles)
    by_symbol = group_candles_by_symbol(candle_rows)
    requested = [normalize_symbol(s) for s in requested_symbols if normalize_symbol(s)]
    requested_set = set(requested)
    rows: list[UniverseSymbolRow] = []
    usable: set[str] = set()
    missing = 0
    under_min = 0

    for symbol in requested:
        count = len(by_symbol.get(symbol, []))
        if count <= 0:
            missing += 1
            rows.append(UniverseSymbolRow(symbol, True, 0, "MISSING", "Symbol requested but not found in candles."))
        elif count < cfg.min_candles_per_symbol:
            under_min += 1
            rows.append(UniverseSymbolRow(symbol, True, count, "WARN", f"Only {count} candles, min required {cfg.min_candles_per_symbol}."))
        else:
            usable.add(symbol)
            rows.append(UniverseSymbolRow(symbol, True, count, "OK", "Symbol is available and has enough candles."))

    extra_symbols = sorted(set(by_symbol) - requested_set)
    for symbol in extra_symbols:
        rows.append(UniverseSymbolRow(symbol, False, len(by_symbol[symbol]), "EXTRA", "Symbol exists in candles but was not requested."))

    filtered = [c for c in candle_rows if c.symbol in usable]
    status = "FAIL" if not usable else "WARN" if missing or under_min else "OK"
    summary = UniverseInputSummary(
        requested_symbols=len(requested),
        candle_symbols=len(by_symbol),
        usable_symbols=len(usable),
        missing_symbols=missing,
        under_min_history_symbols=under_min,
        filtered_candles=len(filtered),
        status=status,
    )
    return summary, rows, filtered


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]


def write_universe_outputs(candles_csv: str | Path, universe_csv: str | Path, out_dir: str | Path, min_candles_per_symbol: int = 100) -> UniverseInputSummary:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    candles = read_candles_csv(candles_csv)
    requested = read_universe_symbols(universe_csv)
    summary, rows, filtered = analyze_universe_input(candles, requested, UniverseInputConfig(min_candles_per_symbol=min_candles_per_symbol))
    write_dict_csv(out / "universe_input_summary.csv", rows_as_dicts([summary]))
    write_dict_csv(out / "universe_input_report.csv", rows_as_dicts(rows))
    write_candles_csv(out / "filtered_candles.csv", filtered)
    return summary


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
