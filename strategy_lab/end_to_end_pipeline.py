#!/usr/bin/env python3
"""End-to-end research runner.

Runs the full non-live chain:

candles.csv
-> candle_features.csv
-> candidate_setups.csv
-> risk_plans.csv
-> generated_trades.csv
-> integrated pipeline reports
-> paper mode reports on pipeline-allowed trades
-> report sanity checks

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from strategy_lab.candle_pipeline import run_candle_pipeline
from strategy_lab.config import PipelineConfig
from strategy_lab.paper_mode import run_paper_mode
from strategy_lab.pipeline import run_pipeline
from strategy_lab.report_sanity import write_report_sanity


@dataclass(frozen=True)
class EndToEndSummary:
    profile: str
    candles: int
    features: int
    candidates: int
    risk_plans: int
    generated_trades: int
    pipeline_candidates: int
    allowed_candidates: int
    executed_trades: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    avg_risk_pct: float
    paper_signals: int
    paper_filled: int
    paper_closed: int
    paper_avg_pnl_pct: float
    sanity_status: str
    sanity_errors: int
    sanity_warnings: int


def write_summary(path: str | Path, summary: EndToEndSummary) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(summary).keys()))
        writer.writeheader()
        writer.writerow(asdict(summary))


def read_csv_rows(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return [], []
    with p.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_dict_csv(path: str | Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    if not fields:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("Z", "").replace("T", " "))


def trade_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(row.get("symbol", "")).strip().upper(),
        str(row.get("side", "")).strip().lower(),
        parse_dt(str(row.get("entry_time", ""))).isoformat(sep=" ", timespec="seconds"),
    )


def write_pipeline_allowed_trades(generated_trades: str | Path, pipeline_decisions: str | Path, out_csv: str | Path) -> int:
    """Write generated trade rows that passed the integrated pipeline gate.

    Paper mode must review the actual strategy candidate, not every raw generated
    setup. This helper joins generated_trades.csv with pipeline_decisions.csv by
    symbol/side/entry_time and keeps only rows with allowed=True.
    """
    generated_rows, generated_fields = read_csv_rows(generated_trades)
    decision_rows, _decision_fields = read_csv_rows(pipeline_decisions)
    allowed_keys = {
        trade_key(row)
        for row in decision_rows
        if str(row.get("allowed", "")).strip().lower() == "true"
    }
    allowed_rows = [row for row in generated_rows if trade_key(row) in allowed_keys]
    write_dict_csv(out_csv, allowed_rows, generated_fields)
    return len(allowed_rows)


def run_end_to_end_pipeline(
    candles_csv: str | Path,
    out_dir: str | Path = "results",
    profile: str = "growth_100_20x",
    min_confidence: float = 50.0,
    cfg: PipelineConfig | None = None,
) -> EndToEndSummary:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    candle_summary = run_candle_pipeline(candles_csv=candles_csv, out_dir=out, min_confidence=min_confidence)
    generated_trades = out / "generated_trades.csv"
    if not generated_trades.exists() or generated_trades.stat().st_size == 0:
        raise RuntimeError("Candle pipeline did not create generated_trades.csv")

    pipeline_summary = run_pipeline(input_csv=generated_trades, out_dir=out, cfg=cfg, profile_name=profile)
    allowed_trades = out / "pipeline_allowed_trades.csv"
    write_pipeline_allowed_trades(generated_trades, out / "pipeline_decisions.csv", allowed_trades)

    # Keep a raw paper audit for diagnostics, but make the primary paper report
    # review the actual pipeline-allowed strategy candidate.
    run_paper_mode(generated_trades_csv=generated_trades, out_dir=out / "paper_raw")
    paper_summary = run_paper_mode(generated_trades_csv=allowed_trades, out_dir=out / "paper")
    sanity = write_report_sanity(out)
    summary = EndToEndSummary(
        profile=profile,
        candles=candle_summary["candles"],
        features=candle_summary["features"],
        candidates=candle_summary["candidates"],
        risk_plans=candle_summary["risk_plans"],
        generated_trades=candle_summary["generated_trades"],
        pipeline_candidates=pipeline_summary.candidates,
        allowed_candidates=pipeline_summary.allowed_candidates,
        executed_trades=pipeline_summary.executed_trades,
        final_cash=pipeline_summary.final_cash,
        ret_pct=pipeline_summary.ret_pct,
        max_dd_pct=pipeline_summary.max_dd_pct,
        pf=pipeline_summary.pf,
        winrate=pipeline_summary.winrate,
        avg_risk_pct=pipeline_summary.avg_risk_pct,
        paper_signals=paper_summary.paper_signals,
        paper_filled=paper_summary.filled_paper,
        paper_closed=paper_summary.closed_paper,
        paper_avg_pnl_pct=paper_summary.avg_pnl_pct,
        sanity_status=sanity.status,
        sanity_errors=sanity.errors,
        sanity_warnings=sanity.warnings,
    )
    write_summary(out / "end_to_end_summary.csv", summary)
    return summary


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--candles", required=True)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--profile", default="growth_100_20x")
    p.add_argument("--min-confidence", type=float, default=50.0)
    args = p.parse_args()

    summary = run_end_to_end_pipeline(
        candles_csv=args.candles,
        out_dir=args.out_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
    )
    print("End-to-end pipeline complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
