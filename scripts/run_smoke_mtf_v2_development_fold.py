#!/usr/bin/env python3
"""Run one frozen SMOKE MTF V2 development symbol/fold job."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_development_backtest_v1 import (
    FundingRate,
    candidate_to_dict,
    contiguous_fold_bounds,
    generate_fold_candidates,
)


def read_funding_csv(path: str | Path) -> list[FundingRate]:
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return []
    rows: list[FundingRate] = []
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "time", "rate"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing funding columns: {sorted(missing)}")
        for row in reader:
            rows.append(
                FundingRate(
                    symbol=str(row["symbol"]).upper(),
                    time=parse_dt(str(row["time"])),
                    rate=float(row["rate"]),
                )
            )
    return sorted(rows, key=lambda item: (item.symbol, item.time))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--funding", required=True)
    parser.add_argument("--funding-summary", required=True)
    parser.add_argument("--fold", required=True, type=int)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--development-start", default="2025-01-01T00:00:00")
    parser.add_argument("--development-end", default="2026-07-01T00:00:00")
    args = parser.parse_args()

    development_start = parse_dt(args.development_start)
    development_end = parse_dt(args.development_end)
    bounds = contiguous_fold_bounds(development_start, development_end, 10)
    if not 0 <= args.fold < len(bounds):
        raise ValueError("fold must be in [0, 9]")
    scan_start, scan_end = bounds[args.fold]
    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    funding = read_funding_csv(args.funding)
    funding_summary = json.loads(Path(args.funding_summary).read_text(encoding="utf-8"))
    candidates, summary = generate_fold_candidates(
        candles,
        fold=args.fold,
        scan_start=scan_start,
        scan_end=scan_end,
        study_end=development_end,
        funding_rates=funding,
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "study_id": "SMOKE_MTF_V2_DEVELOPMENT_PROFITABILITY_V2",
        "mode": "FROZEN_DEVELOPMENT_TRADE_CANDIDATES",
        "recognition_freeze_sha": "492eee9fdba5993b7f518e9a1ff38576e8b14285",
        "event_layer": "excluded_from_primary_development_due_no_causal_historical_point_in_time_snapshot",
        "funding_rows": len(funding),
        "funding_coverage_status": str(funding_summary.get("status") or "UNKNOWN"),
        "funding_summary": funding_summary,
        "summary": summary,
        "candidates": [candidate_to_dict(row) for row in candidates],
    }
    (out / "fold_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "summary.json").write_text(
        json.dumps({**summary, "funding_rows": len(funding)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fields = list(candidate_to_dict(candidates[0]).keys()) if candidates else [
        "symbol", "side", "fold", "entry_time", "entry", "stop", "target",
        "exit_time", "exit_price", "exit_reason", "gross_return_fraction",
        "funding_return_fraction", "net_return_fraction", "structural_risk_fraction",
        "event_risk_multiplier", "planned_rr", "quality_score",
        "target_timeframe", "target_source",
    ]
    with (out / "fold_candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in candidates:
            writer.writerow(candidate_to_dict(row))
    print(
        f"fold={args.fold} symbol={summary['symbol']} "
        f"entry_ready={summary['entry_ready_candidates']} candidates={len(candidates)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
