#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from strategy_lab.rolling_symbol_strength import CapitalConfig, CostConfig, RollingConfig, load_trades_csv, parse_dt, run_rolling


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades-csv", default="data/sample_runner_trades.csv")
    parser.add_argument("--out", default="results/sample_rolling_report.csv")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-05-31")
    args = parser.parse_args()

    trades = load_trades_csv(args.trades_csv)
    rows = []
    for lookback in [30, 60, 90]:
        for rebalance in [7, 14, 30]:
            for top_n in [5, 8, 12, 20]:
                for lev in [10, 15, 20, 25]:
                    result = run_rolling(
                        trades,
                        parse_dt(args.start),
                        parse_dt(args.end),
                        RollingConfig(lookback, rebalance, top_n),
                        CapitalConfig(500, 0.005, lev, 2, 0.20, False),
                        CostConfig(0.0010, 0.0002),
                    )
                    rows.append({
                        "setup": result.setup,
                        "lev": lev,
                        "trades": result.trades,
                        "skipped": result.skipped,
                        "final_cash": round(result.final_cash, 2),
                        "ret_pct": round(result.ret_pct, 2),
                        "max_dd_pct": round(result.max_dd_pct, 2),
                        "pf": round(result.pf, 3),
                        "winrate": round(result.winrate, 2),
                        "max_loss_streak": result.max_loss_streak,
                        "symbols_positive": result.symbols_positive,
                        "symbols_traded": result.symbols_traded,
                        "avg_selected": round(result.avg_selected, 2),
                        "windows": result.windows,
                    })

    rows.sort(key=lambda r: (r["ret_pct"], -r["max_dd_pct"], r["pf"]), reverse=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows -> {out}")
    for row in rows[:10]:
        print(row)


if __name__ == "__main__":
    main()
