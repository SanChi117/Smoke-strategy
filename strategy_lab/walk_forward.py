#!/usr/bin/env python3
"""Walk-forward research skeleton.

Splits an OHLCV candle dataset into chronological windows and runs the existing
end-to-end research pipeline independently on each window.

This is a first skeleton, not final optimization. It validates that the
strategy can be tested across multiple time slices instead of one fixed sample.

Research only. No live trading. No exchange keys.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from statistics import mean
from typing import Iterable

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline
from strategy_lab.market_data import Candle, read_candles_csv


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    start_time: object
    end_time: object
    candles: int
    symbols: int


@dataclass(frozen=True)
class WalkForwardRow:
    window_index: int
    start_time: object
    end_time: object
    candles: int
    symbols: int
    generated_trades: int
    allowed_candidates: int
    executed_trades: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    avg_risk_pct: float
    status: str
    reports_dir: str
    error: str


@dataclass(frozen=True)
class WalkForwardReportRow:
    metric: str
    value: str
    note: str


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


def row_dicts(rows: Iterable[object]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        item = asdict(row)
        for key in ["start_time", "end_time"]:
            if key in item and hasattr(item[key], "isoformat"):
                item[key] = item[key].isoformat(timespec="seconds")
        out.append(item)
    return out


def make_windows(candles: list[Candle], window_days: int = 30, step_days: int = 15, min_candles: int = 100) -> list[WalkForwardWindow]:
    if not candles:
        return []
    sorted_rows = sorted(candles, key=lambda c: c.time)
    start = sorted_rows[0].time
    end = sorted_rows[-1].time
    window_delta = timedelta(days=window_days)
    step_delta = timedelta(days=step_days)
    windows: list[WalkForwardWindow] = []
    idx = 1
    cursor = start
    while cursor + window_delta <= end:
        win_end = cursor + window_delta
        win_rows = [c for c in sorted_rows if cursor <= c.time < win_end]
        symbols = {c.symbol for c in win_rows}
        if len(win_rows) >= min_candles:
            windows.append(WalkForwardWindow(
                index=idx,
                start_time=cursor,
                end_time=win_end,
                candles=len(win_rows),
                symbols=len(symbols),
            ))
            idx += 1
        cursor = cursor + step_delta
    return windows


def write_window_candles(path: Path, candles: list[Candle], window: WalkForwardWindow) -> None:
    rows = [c for c in candles if window.start_time <= c.time < window.end_time]
    out_rows = []
    for c in rows:
        out_rows.append({
            "symbol": c.symbol,
            "time": c.time.isoformat(timespec="seconds") if hasattr(c.time, "isoformat") else str(c.time),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        })
    write_dict_csv(path, out_rows)


def pct(value: float) -> str:
    return str(round(value, 4))


def build_walk_forward_report(rows: list[WalkForwardRow]) -> list[WalkForwardReportRow]:
    total = len(rows)
    ok_rows = [r for r in rows if r.status == "OK"]
    error_rows = [r for r in rows if r.status != "OK"]
    profitable = [r for r in ok_rows if r.ret_pct > 0]
    losing = [r for r in ok_rows if r.ret_pct < 0]
    flat = [r for r in ok_rows if r.ret_pct == 0]
    executed = [r for r in ok_rows if r.executed_trades > 0]
    avg_ret = mean([r.ret_pct for r in ok_rows]) if ok_rows else 0.0
    avg_dd = mean([r.max_dd_pct for r in ok_rows]) if ok_rows else 0.0
    avg_trades = mean([r.executed_trades for r in ok_rows]) if ok_rows else 0.0
    worst = min(ok_rows, key=lambda r: r.ret_pct) if ok_rows else None
    best = max(ok_rows, key=lambda r: r.ret_pct) if ok_rows else None
    stability_score = 0.0
    if total:
        stability_score += len(ok_rows) / total * 40.0
    if ok_rows:
        stability_score += len(profitable) / len(ok_rows) * 35.0
        stability_score += len(executed) / len(ok_rows) * 15.0
        if avg_dd > -20:
            stability_score += 10.0
    status = "PASS" if stability_score >= 70 else "WATCH" if stability_score >= 45 else "FAIL"

    report = [
        WalkForwardReportRow("windows_total", str(total), "Total walk-forward windows."),
        WalkForwardReportRow("windows_ok", str(len(ok_rows)), "Windows completed without pipeline errors."),
        WalkForwardReportRow("windows_error", str(len(error_rows)), "Windows that failed and were reported instead of hidden."),
        WalkForwardReportRow("profitable_windows", str(len(profitable)), "OK windows with ret_pct > 0."),
        WalkForwardReportRow("losing_windows", str(len(losing)), "OK windows with ret_pct < 0."),
        WalkForwardReportRow("flat_windows", str(len(flat)), "OK windows with ret_pct = 0."),
        WalkForwardReportRow("executed_windows", str(len(executed)), "OK windows with at least one executed trade."),
        WalkForwardReportRow("avg_ret_pct", pct(avg_ret), "Average ret_pct across OK windows."),
        WalkForwardReportRow("avg_max_dd_pct", pct(avg_dd), "Average max_dd_pct across OK windows."),
        WalkForwardReportRow("avg_executed_trades", pct(avg_trades), "Average executed trades across OK windows."),
        WalkForwardReportRow("stability_score", pct(stability_score), "Simple 0-100 score for research stability across windows."),
        WalkForwardReportRow("stability_status", status, "PASS/WATCH/FAIL based on stability_score."),
    ]
    if best:
        report.append(WalkForwardReportRow("best_window", str(best.window_index), f"ret_pct={best.ret_pct}, reports={best.reports_dir}"))
    if worst:
        report.append(WalkForwardReportRow("worst_window", str(worst.window_index), f"ret_pct={worst.ret_pct}, reports={worst.reports_dir}"))
    if error_rows:
        report.append(WalkForwardReportRow("first_error_window", str(error_rows[0].window_index), error_rows[0].error))
    return report


def run_walk_forward(
    candles_csv: str | Path,
    out_dir: str | Path = "results/walk_forward",
    profile: str = "growth_100_20x",
    min_confidence: float = 40.0,
    window_days: int = 30,
    step_days: int = 15,
    min_candles: int = 100,
) -> list[WalkForwardRow]:
    candles = read_candles_csv(candles_csv)
    windows = make_windows(candles, window_days=window_days, step_days=step_days, min_candles=min_candles)
    out = Path(out_dir)
    windows_dir = out / "windows"
    reports_dir = out / "reports"
    out.mkdir(parents=True, exist_ok=True)

    write_dict_csv(out / "walk_forward_windows.csv", row_dicts(windows))
    rows: list[WalkForwardRow] = []
    for window in windows:
        window_name = f"window_{window.index:03d}"
        window_csv = windows_dir / f"{window_name}.csv"
        report_dir = reports_dir / window_name
        write_window_candles(window_csv, candles, window)
        try:
            summary = run_end_to_end_pipeline(
                candles_csv=window_csv,
                out_dir=report_dir,
                profile=profile,
                min_confidence=min_confidence,
            )
            rows.append(WalkForwardRow(
                window_index=window.index,
                start_time=window.start_time,
                end_time=window.end_time,
                candles=window.candles,
                symbols=window.symbols,
                generated_trades=summary.generated_trades,
                allowed_candidates=summary.allowed_candidates,
                executed_trades=summary.executed_trades,
                final_cash=summary.final_cash,
                ret_pct=summary.ret_pct,
                max_dd_pct=summary.max_dd_pct,
                pf=summary.pf,
                winrate=summary.winrate,
                avg_risk_pct=summary.avg_risk_pct,
                status="OK",
                reports_dir=str(report_dir),
                error="",
            ))
        except Exception as exc:  # defensive: WFO should report bad windows, not hide them
            rows.append(WalkForwardRow(
                window_index=window.index,
                start_time=window.start_time,
                end_time=window.end_time,
                candles=window.candles,
                symbols=window.symbols,
                generated_trades=0,
                allowed_candidates=0,
                executed_trades=0,
                final_cash=0.0,
                ret_pct=0.0,
                max_dd_pct=0.0,
                pf=0.0,
                winrate=0.0,
                avg_risk_pct=0.0,
                status="ERROR",
                reports_dir=str(report_dir),
                error=str(exc),
            ))
    write_dict_csv(out / "walk_forward_summary.csv", row_dicts(rows))
    write_dict_csv(out / "walk_forward_report.csv", row_dicts(build_walk_forward_report(rows)))
    return rows
