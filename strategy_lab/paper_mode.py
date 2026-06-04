#!/usr/bin/env python3
"""Paper mode skeleton with lifecycle journal.

Converts generated research trades into paper signals and simulates a paper-only
lifecycle:

OPEN_SIGNAL -> FILLED_PAPER -> CLOSED_PAPER

Research only. No exchange calls. No order execution.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from strategy_lab.paper_review import run_paper_review


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
class PaperJournalEvent:
    paper_id: str
    event_order: int
    event: str
    event_time: str
    symbol: str
    side: str
    price: float
    status_after: str
    note: str


@dataclass(frozen=True)
class PaperPosition:
    paper_id: str
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    stop: float
    target: float
    status: str
    close_reason: str
    pnl_pct: float
    setup_type: str
    risk_grade: str


@dataclass(frozen=True)
class PaperSummary:
    source_rows: int
    paper_signals: int
    filled_paper: int
    closed_paper: int
    long_signals: int
    short_signals: int
    winners: int
    losers: int
    avg_pnl_pct: float
    review_approved: int
    review_watch: int
    review_rejected: int
    review_status: str
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


def first_float(row: dict[str, str], keys: list[str], default: float = 0.0) -> float:
    for key in keys:
        value = to_float(row.get(key), 0.0)
        if value > 0:
            return value
    return default


def first_text(row: dict[str, str], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return default


def pnl_pct(side: str, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    if side == "short":
        return round((entry - exit_price) / entry * 100.0, 6)
    return round((exit_price - entry) / entry * 100.0, 6)


def close_reason_from_row(row: dict[str, str], exit_price: float, stop: float, target: float) -> str:
    reason = str(row.get("exit_reason", "")).strip()
    if reason:
        return reason
    if target > 0 and abs(exit_price - target) / target < 0.000001:
        return "take_profit"
    if stop > 0 and abs(exit_price - stop) / stop < 0.000001:
        return "stop_loss"
    return "research_exit"


def target_from_row(row: dict[str, str], entry: float, stop: float, exit_price: float) -> float:
    target = first_float(row, ["target", "tp", "take_profit", "target_price"])
    if target > 0:
        return target
    if exit_price > 0:
        return exit_price
    r_mult = to_float(row.get("r_mult"), 0.0)
    risk = abs(entry - stop)
    side = str(row.get("side", "long")).strip().lower() or "long"
    if risk > 0 and r_mult > 0:
        return round(entry - risk * r_mult, 8) if side == "short" else round(entry + risk * r_mult, 8)
    return entry


def signal_from_row(row: dict[str, str], idx: int, source: str = "generated_trades") -> PaperSignal | None:
    symbol = str(row.get("symbol", "")).strip().upper()
    side = str(row.get("side", "long")).strip().lower() or "long"
    entry = first_float(row, ["entry", "entry_price", "open_price"])
    stop = first_float(row, ["stop", "sl", "stop_loss", "stop_price"])
    exit_price = first_float(row, ["exit", "exit_price", "close_price"])
    target = target_from_row(row, entry, stop, exit_price)
    if not symbol or entry <= 0 or stop <= 0 or target <= 0:
        return None
    return PaperSignal(
        paper_id=f"PAPER-{idx:06d}",
        symbol=symbol,
        side=side,
        entry_time=first_text(row, ["entry_time", "time", "timestamp"]),
        entry=entry,
        stop=stop,
        target=target,
        setup_type=first_text(row, ["setup_type", "kind", "strategy"]),
        risk_grade=first_text(row, ["risk_grade", "quality_grade"]),
        target_policy=first_text(row, ["target_policy", "tp_policy"]),
        status="OPEN_SIGNAL",
        source=source,
    )


def make_paper_signals(rows: list[dict[str, str]], source: str = "generated_trades") -> list[PaperSignal]:
    signals: list[PaperSignal] = []
    for idx, row in enumerate(rows, start=1):
        signal = signal_from_row(row, idx, source=source)
        if signal is not None:
            signals.append(signal)
    return signals


def build_lifecycle(rows: list[dict[str, str]], signals: list[PaperSignal]) -> tuple[list[PaperJournalEvent], list[PaperPosition]]:
    events: list[PaperJournalEvent] = []
    positions: list[PaperPosition] = []
    signal_by_id = {signal.paper_id: signal for signal in signals}
    for idx, row in enumerate(rows, start=1):
        paper_id = f"PAPER-{idx:06d}"
        signal = signal_by_id.get(paper_id)
        if signal is None:
            continue
        exit_price = first_float(row, ["exit", "exit_price", "close_price"], signal.target)
        exit_time = first_text(row, ["exit_time", "close_time"], signal.entry_time)
        reason = close_reason_from_row(row, exit_price, signal.stop, signal.target)
        events.append(PaperJournalEvent(signal.paper_id, 1, "OPEN_SIGNAL", signal.entry_time, signal.symbol, signal.side, signal.entry, "OPEN_SIGNAL", "Paper signal created from research trade."))
        events.append(PaperJournalEvent(signal.paper_id, 2, "FILLED_PAPER", signal.entry_time, signal.symbol, signal.side, signal.entry, "FILLED_PAPER", "Paper fill at research entry price."))
        events.append(PaperJournalEvent(signal.paper_id, 3, "CLOSED_PAPER", exit_time, signal.symbol, signal.side, exit_price, "CLOSED_PAPER", f"Paper close reason: {reason}."))
        positions.append(PaperPosition(
            paper_id=signal.paper_id,
            symbol=signal.symbol,
            side=signal.side,
            entry_time=signal.entry_time,
            exit_time=exit_time,
            entry=signal.entry,
            exit=exit_price,
            stop=signal.stop,
            target=signal.target,
            status="CLOSED_PAPER",
            close_reason=reason,
            pnl_pct=pnl_pct(signal.side, signal.entry, exit_price),
            setup_type=signal.setup_type,
            risk_grade=signal.risk_grade,
        ))
    return events, positions


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
    events, positions = build_lifecycle(rows, signals)
    out = Path(out_dir)
    long_count = sum(1 for signal in signals if signal.side == "long")
    short_count = sum(1 for signal in signals if signal.side == "short")
    winners = sum(1 for position in positions if position.pnl_pct > 0)
    losers = sum(1 for position in positions if position.pnl_pct < 0)
    avg_pnl = round(sum(p.pnl_pct for p in positions) / len(positions), 6) if positions else 0.0
    write_dict_csv(out / "paper_signals.csv", rows_as_dicts(signals))
    write_dict_csv(out / "paper_journal.csv", rows_as_dicts(events))
    write_dict_csv(out / "paper_positions.csv", rows_as_dicts(positions))
    review = run_paper_review(out / "paper_positions.csv", out)
    summary = PaperSummary(
        source_rows=len(rows),
        paper_signals=len(signals),
        filled_paper=len(positions),
        closed_paper=len(positions),
        long_signals=long_count,
        short_signals=short_count,
        winners=winners,
        losers=losers,
        avg_pnl_pct=avg_pnl,
        review_approved=review.approved,
        review_watch=review.watch,
        review_rejected=review.rejected,
        review_status=review.status,
        status="OK" if signals else "EMPTY",
    )
    write_dict_csv(out / "paper_summary.csv", rows_as_dicts([summary]))
    return summary
