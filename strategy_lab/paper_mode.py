#!/usr/bin/env python3
"""Paper mode skeleton.

Converts generated research trades into paper signals and a paper journal.

Research only. No exchange calls. No order execution.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PaperSignal:
    paper_id: str
    symbol: str
    side: str
    entry_time: str
    entry: float
    stop: float
    target: float
    setup_type: str
    risk_grade: str
    target_policy: str
    status: str
    source: str


@dataclass(frozen=True)
class PaperSummary:
    source_rows: int
    paper_signals: int
    long_signals: int
    short_signals: int
    status: str


def read_generated_trades(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def make_paper_signals(rows: list[dict[str, str]], source: str = "generated_trades") -> list[PaperSignal]:
    signals: list[PaperSignal] = []
    for idx, row in enumerate(rows, start=1):
        symbol = str(row.get("symbol", "")).strip().upper()
        side = str(row.get("side", "long")).strip().lower() or "long"
        entry = to_float(row.get("entry"))
        stop = to_float(row.get("stop"))
        target = to_float(row.get("target"))
        if not symbol or entry <= 0 or stop <= 0 or target <= 0:
            continue
        signals.append(PaperSignal(
            paper_id=f"PAPER-{idx:06d}",
            symbol=symbol,
            side=side,
            entry_time=str(row.get("entry_time", "")),
            entry=entry,
            stop=stop,
            target=target,
            setup_type=str(row.get("setup_type", "")),
            risk_grade=str(row.get("risk_grade", "")),
            target_policy=str(row.get("target_policy", "")),
            status="OPEN_SIGNAL",
            source=source,
        ))
    return signals


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


def run_paper_mode(generated_trades_csv: str | Path, out_dir: str | Path = "results/paper") -> PaperSummary:
    rows = read_generated_trades(generated_trades_csv)
    signals = make_paper_signals(rows)
    out = Path(out_dir)
    long_count = sum(1 for signal in signals if signal.side == "long")
    short_count = sum(1 for signal in signals if signal.side == "short")
    summary = PaperSummary(
        source_rows=len(rows),
        paper_signals=len(signals),
        long_signals=long_count,
        short_signals=short_count,
        status="OK" if signals else "EMPTY",
    )
    write_dict_csv(out / "paper_signals.csv", rows_as_dicts(signals))
    write_dict_csv(out / "paper_summary.csv", rows_as_dicts([summary]))
    return summary
