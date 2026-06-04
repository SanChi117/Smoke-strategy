#!/usr/bin/env python3
"""Walk-forward parameter grid skeleton.

Runs the existing walk-forward research flow for a small parameter grid and
compares stability across parameter values.

Current first parameter:
- min_confidence

This is a research skeleton, not final optimizer.

Research only. No live trading. No exchange keys.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

from strategy_lab.walk_forward import run_walk_forward


@dataclass(frozen=True)
class ParameterGridRow:
    param_name: str
    param_value: str
    reports_dir: str
    windows_total: int
    windows_ok: int
    windows_error: int
    profitable_windows: int
    losing_windows: int
    executed_windows: int
    avg_ret_pct: float
    avg_max_dd_pct: float
    avg_executed_trades: float
    stability_score: float
    stability_status: str
    best_window: str
    worst_window: str


@dataclass(frozen=True)
class ParameterGridReportRow:
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


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]


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


def grid_value_label(value: float) -> str:
    text = str(value).replace(".", "_")
    return f"min_confidence_{text}"


def run_parameter_grid(
    candles_csv: str | Path,
    out_dir: str | Path = "results/parameter_grid",
    profile: str = "growth_100_20x",
    min_confidence_values: Iterable[float] = (30.0, 40.0, 50.0),
    window_days: int = 30,
    step_days: int = 15,
    min_candles: int = 100,
) -> list[ParameterGridRow]:
    out = Path(out_dir)
    rows: list[ParameterGridRow] = []
    for value in min_confidence_values:
        label = grid_value_label(float(value))
        reports_dir = out / label
        run_walk_forward(
            candles_csv=candles_csv,
            out_dir=reports_dir,
            profile=profile,
            min_confidence=float(value),
            window_days=window_days,
            step_days=step_days,
            min_candles=min_candles,
        )
        metrics = read_metric_rows(reports_dir / "walk_forward_report.csv")
        rows.append(ParameterGridRow(
            param_name="min_confidence",
            param_value=str(float(value)),
            reports_dir=str(reports_dir),
            windows_total=to_int(metrics.get("windows_total")),
            windows_ok=to_int(metrics.get("windows_ok")),
            windows_error=to_int(metrics.get("windows_error")),
            profitable_windows=to_int(metrics.get("profitable_windows")),
            losing_windows=to_int(metrics.get("losing_windows")),
            executed_windows=to_int(metrics.get("executed_windows")),
            avg_ret_pct=to_float(metrics.get("avg_ret_pct")),
            avg_max_dd_pct=to_float(metrics.get("avg_max_dd_pct")),
            avg_executed_trades=to_float(metrics.get("avg_executed_trades")),
            stability_score=to_float(metrics.get("stability_score")),
            stability_status=str(metrics.get("stability_status", "missing")),
            best_window=str(metrics.get("best_window", "")),
            worst_window=str(metrics.get("worst_window", "")),
        ))

    write_dict_csv(out / "parameter_grid_summary.csv", rows_as_dicts(rows))
    write_dict_csv(out / "parameter_grid_report.csv", rows_as_dicts(build_parameter_grid_report(rows)))
    return rows


def build_parameter_grid_report(rows: list[ParameterGridRow]) -> list[ParameterGridReportRow]:
    if not rows:
        return [ParameterGridReportRow("status", "EMPTY", "No parameter rows were generated.")]
    sorted_by_score = sorted(rows, key=lambda r: (r.stability_score, r.avg_ret_pct, r.executed_windows), reverse=True)
    best = sorted_by_score[0]
    avg_score = mean([r.stability_score for r in rows]) if rows else 0.0
    pass_rows = [r for r in rows if r.stability_status == "PASS"]
    watch_rows = [r for r in rows if r.stability_status == "WATCH"]
    fail_rows = [r for r in rows if r.stability_status == "FAIL"]
    report = [
        ParameterGridReportRow("grid_rows", str(len(rows)), "Number of tested parameter values."),
        ParameterGridReportRow("best_param_name", best.param_name, "Best parameter name by stability score."),
        ParameterGridReportRow("best_param_value", best.param_value, "Best parameter value by stability score, then avg_ret_pct."),
        ParameterGridReportRow("best_stability_score", str(round(best.stability_score, 4)), "Best stability score."),
        ParameterGridReportRow("best_avg_ret_pct", str(round(best.avg_ret_pct, 4)), "Best row average return percent."),
        ParameterGridReportRow("best_executed_windows", str(best.executed_windows), "Executed windows for best row."),
        ParameterGridReportRow("avg_stability_score", str(round(avg_score, 4)), "Average stability score across grid rows."),
        ParameterGridReportRow("pass_rows", str(len(pass_rows)), "Rows with PASS stability status."),
        ParameterGridReportRow("watch_rows", str(len(watch_rows)), "Rows with WATCH stability status."),
        ParameterGridReportRow("fail_rows", str(len(fail_rows)), "Rows with FAIL stability status."),
    ]
    return report
