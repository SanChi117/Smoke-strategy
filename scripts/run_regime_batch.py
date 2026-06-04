#!/usr/bin/env python3
"""Run end-to-end research pipeline for multiple deterministic regimes.

By default this script generates trend/range/high-vol/mixed synthetic samples,
runs the full end-to-end pipeline for each, and writes a compact comparison
report.

Research only. Synthetic data. No exchange calls. No live trading.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.generate_regime_samples import generate_high_vol, generate_range, generate_trend, write_csv
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


@dataclass(frozen=True)
class RegimeBatchRow:
    regime: str
    candles_csv: str
    reports_dir: str
    candles: int
    features: int
    generated_trades: int
    allowed_candidates: int
    executed_trades: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    avg_risk_pct: float
    candle_winrate_pct: str
    candle_avg_r: str
    candle_total_r: str
    best_setup_type: str
    worst_setup_type: str
    most_common_exit: str


def write_dict_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_metric(path: Path, metric: str) -> str:
    if not path.exists():
        return "missing"
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("metric") == metric:
                return str(row.get("value", ""))
    return "missing"


def generate_samples(out_dir: Path, symbols: int, hours: int) -> dict[str, Path]:
    trend = generate_trend(symbols, hours)
    range_rows = generate_range(symbols, hours)
    high_vol = generate_high_vol(symbols, hours)
    mixed = trend + range_rows + high_vol
    paths = {
        "trend": out_dir / "trend_candles.csv",
        "range": out_dir / "range_candles.csv",
        "high_vol": out_dir / "high_vol_candles.csv",
        "mixed": out_dir / "mixed_regime_candles.csv",
    }
    write_csv(paths["trend"], trend)
    write_csv(paths["range"], range_rows)
    write_csv(paths["high_vol"], high_vol)
    write_csv(paths["mixed"], mixed)
    return paths


def run_batch(sample_paths: dict[str, Path], reports_root: Path, profile: str, min_confidence: float) -> list[RegimeBatchRow]:
    rows: list[RegimeBatchRow] = []
    for regime, candles_path in sample_paths.items():
        out_dir = reports_root / regime
        summary = run_end_to_end_pipeline(
            candles_csv=candles_path,
            out_dir=out_dir,
            profile=profile,
            min_confidence=min_confidence,
        )
        candle_report = out_dir / "candle_research_report.csv"
        rows.append(RegimeBatchRow(
            regime=regime,
            candles_csv=str(candles_path),
            reports_dir=str(out_dir),
            candles=summary.candles,
            features=summary.features,
            generated_trades=summary.generated_trades,
            allowed_candidates=summary.allowed_candidates,
            executed_trades=summary.executed_trades,
            final_cash=summary.final_cash,
            ret_pct=summary.ret_pct,
            max_dd_pct=summary.max_dd_pct,
            pf=summary.pf,
            winrate=summary.winrate,
            avg_risk_pct=summary.avg_risk_pct,
            candle_winrate_pct=read_metric(candle_report, "winrate_pct"),
            candle_avg_r=read_metric(candle_report, "avg_r"),
            candle_total_r=read_metric(candle_report, "total_r"),
            best_setup_type=read_metric(candle_report, "best_setup_type"),
            worst_setup_type=read_metric(candle_report, "worst_setup_type"),
            most_common_exit=read_metric(candle_report, "most_common_exit"),
        ))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-dir", default="data/regime_samples")
    parser.add_argument("--reports-dir", default="results/regime_batch")
    parser.add_argument("--symbols", type=int, default=4)
    parser.add_argument("--hours", type=int, default=1200)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence", type=float, default=35.0)
    parser.add_argument("--use-existing", action="store_true", help="Use existing sample files instead of regenerating them.")
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir)
    reports_dir = Path(args.reports_dir)
    if args.use_existing:
        sample_paths = {
            "trend": sample_dir / "trend_candles.csv",
            "range": sample_dir / "range_candles.csv",
            "high_vol": sample_dir / "high_vol_candles.csv",
            "mixed": sample_dir / "mixed_regime_candles.csv",
        }
    else:
        sample_paths = generate_samples(sample_dir, args.symbols, args.hours)

    rows = run_batch(sample_paths, reports_dir, args.profile, args.min_confidence)
    write_dict_csv(reports_dir / "regime_batch_summary.csv", [asdict(row) for row in rows])

    print("Regime batch complete")
    print(f"Samples: {sample_dir}")
    print(f"Reports: {reports_dir}")
    print("regime, generated_trades, executed_trades, ret_pct, max_dd_pct, candle_avg_r, best_setup_type")
    for row in rows:
        print(f"{row.regime}, {row.generated_trades}, {row.executed_trades}, {row.ret_pct}, {row.max_dd_pct}, {row.candle_avg_r}, {row.best_setup_type}")
    print(reports_dir / "regime_batch_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
