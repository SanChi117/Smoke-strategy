#!/usr/bin/env python3
"""Sanity checks for generated research reports.

These checks do not prove profitability. They flag suspicious research outputs
that should not be silently accepted, for example:
- too few generated or executed trades
- too many time-stop exits
- weak average R
- data quality errors
- weak walk-forward stability
- blocked paper decision

Research only. No live trading.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ReportSanityConfig:
    min_generated_trades: int = 5
    min_executed_trades: int = 1
    min_candle_avg_r: float = -0.10
    max_time_stop_pct: float = 65.0
    min_wfo_stability_score: float = 45.0
    max_data_quality_errors: int = 0


@dataclass(frozen=True)
class ReportSanityIssue:
    level: str
    check: str
    metric: str
    value: str
    threshold: str
    message: str


@dataclass(frozen=True)
class ReportSanitySummary:
    checks: int
    errors: int
    warnings: int
    status: str


def read_csv_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def read_metric_rows(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    out: dict[str, str] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            metric = row.get("metric")
            if metric:
                out[metric] = str(row.get("value", ""))
    return out


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def to_int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def add_issue(issues: list[ReportSanityIssue], level: str, check: str, metric: str, value: object, threshold: object, message: str) -> None:
    issues.append(ReportSanityIssue(level, check, metric, str(value), str(threshold), message))


def run_report_sanity_checks(out_dir: str | Path, cfg: ReportSanityConfig | None = None) -> tuple[ReportSanitySummary, list[ReportSanityIssue]]:
    cfg = cfg or ReportSanityConfig()
    out = Path(out_dir)
    issues: list[ReportSanityIssue] = []
    checks = 0

    data_quality = read_csv_first(out / "data_quality_summary.csv")
    if data_quality:
        checks += 1
        errors = to_int(data_quality.get("errors"))
        if errors > cfg.max_data_quality_errors:
            add_issue(issues, "error", "data_quality", "errors", errors, cfg.max_data_quality_errors, "Data quality errors are present.")

    end_to_end = read_csv_first(out / "end_to_end_summary.csv")
    executed = 0
    if end_to_end:
        checks += 1
        generated = to_int(end_to_end.get("generated_trades"))
        executed = to_int(end_to_end.get("executed_trades"))
        if generated < cfg.min_generated_trades:
            add_issue(issues, "warning", "trade_count", "generated_trades", generated, cfg.min_generated_trades, "Too few generated trades for reliable interpretation.")
        if executed < cfg.min_executed_trades:
            add_issue(issues, "warning", "trade_count", "executed_trades", executed, cfg.min_executed_trades, "No or too few executed trades after filters.")

    paper_decision = read_csv_first(out / "paper" / "paper_decision_summary.csv")
    if paper_decision:
        checks += 1
        decision = str(paper_decision.get("decision", "")).strip().upper()
        reason = str(paper_decision.get("reason", ""))
        if decision == "BLOCK":
            # Paper review is currently run on raw generated research trades, not
            # only on pipeline-allowed trades. A paper BLOCK is therefore a review
            # warning for this end-to-end research report, not a hard data failure.
            level = "warning" if executed == 0 else "error"
            add_issue(issues, level, "paper_decision", "decision", decision, "PASS/WATCH", f"Paper decision blocked this run: {reason}")
        elif decision == "WATCH":
            add_issue(issues, "warning", "paper_decision", "decision", decision, "PASS", f"Paper decision requires review: {reason}")
        elif decision and decision != "PASS":
            add_issue(issues, "warning", "paper_decision", "decision", decision, "PASS/WATCH/BLOCK", "Unknown paper decision value.")

    candle_report = read_metric_rows(out / "candle_research_report.csv")
    if candle_report:
        checks += 1
        avg_r = to_float(candle_report.get("avg_r"))
        time_stop = to_float(candle_report.get("time_stop_count"))
        simulated = max(1.0, to_float(candle_report.get("simulated_exits"), 1.0))
        time_stop_pct = time_stop / simulated * 100.0
        if avg_r < cfg.min_candle_avg_r:
            add_issue(issues, "warning", "candle_performance", "avg_r", round(avg_r, 6), cfg.min_candle_avg_r, "Average R is weak in candle simulation.")
        if time_stop_pct > cfg.max_time_stop_pct:
            add_issue(issues, "warning", "exit_quality", "time_stop_pct", round(time_stop_pct, 2), cfg.max_time_stop_pct, "Too many trades exit by time-stop.")

    wfo_report = read_metric_rows(out / "walk_forward_report.csv")
    if wfo_report:
        checks += 1
        stability = to_float(wfo_report.get("stability_score"))
        windows_ok = to_int(wfo_report.get("windows_ok"))
        executed_windows = to_int(wfo_report.get("executed_windows"))
        if stability < cfg.min_wfo_stability_score:
            add_issue(issues, "warning", "walk_forward", "stability_score", round(stability, 4), cfg.min_wfo_stability_score, "Walk-forward stability is weak.")
        if windows_ok > 0 and executed_windows == 0:
            add_issue(issues, "warning", "walk_forward", "executed_windows", executed_windows, ">0", "No WFO windows executed trades.")

    if checks == 0:
        add_issue(issues, "error", "reports_missing", "checks", 0, ">0", "No known report files found for sanity checks.")

    errors = sum(1 for issue in issues if issue.level == "error")
    warnings = sum(1 for issue in issues if issue.level == "warning")
    status = "FAIL" if errors else "WARN" if warnings else "OK"
    return ReportSanitySummary(checks=checks, errors=errors, warnings=warnings, status=status), issues


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]


def write_report_sanity(out_dir: str | Path, cfg: ReportSanityConfig | None = None) -> ReportSanitySummary:
    out = Path(out_dir)
    summary, issues = run_report_sanity_checks(out, cfg)
    write_dict_csv(out / "report_sanity_summary.csv", rows_as_dicts([summary]))
    write_dict_csv(out / "report_sanity_issues.csv", rows_as_dicts(issues))
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
