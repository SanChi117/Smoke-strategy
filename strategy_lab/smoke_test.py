#!/usr/bin/env python3
"""Smoke test for Smoke Strategy Lab."""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.rolling_symbol_strength import (
    CapitalConfig,
    CostConfig,
    RollingConfig,
    load_trades_csv,
    parse_dt,
    run_rolling,
)


def make_sample_csv(path: Path) -> None:
    start = datetime(2026, 1, 1)
    rows = []
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    for i in range(120):
        symbol = symbols[i % len(symbols)]
        entry_time = start + timedelta(days=i)
        exit_time = entry_time + timedelta(hours=12)
        if symbol in {"AAAUSDT", "BBBUSDT"}:
            r = 2.5 if i % 3 != 0 else -1.0
        else:
            r = -1.0 if i % 3 != 0 else 2.0
        entry = 100.0
        stop = 98.0
        exit_p = entry + r * (entry - stop)
        rows.append(
            {
                "symbol": symbol,
                "side": "long",
                "entry_time": entry_time.isoformat(),
                "exit_time": exit_time.isoformat(),
                "entry": entry,
                "stop": stop,
                "exit": exit_p,
                "r_mult": r,
                "kind": "runner",
                "source": "smoke",
            }
        )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "sample_trades.csv"
        make_sample_csv(csv_path)
        trades = load_trades_csv(csv_path)
        result = run_rolling(
            trades,
            parse_dt("2026-01-01"),
            parse_dt("2026-04-30"),
            RollingConfig(lookback_days=14, rebalance_days=7, top_n=2),
            CapitalConfig(initial_cash=500, risk_pct=0.02, leverage=10, max_positions=2),
            CostConfig(fee_rate=0.0008, slippage_rate=0.0),
        )
        print(result)
        assert result.trades > 0, "expected trades"
        assert result.final_cash > 500, "expected profitable sample"
        assert result.symbols_traded <= 4, "smoke selector should keep symbols bounded"
    print("SMOKE TEST OK")


if __name__ == "__main__":
    main()
