#!/usr/bin/env python3
"""Regression test for all-candidate shadow outcome history."""

from __future__ import annotations

import csv
import importlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.live_market import ClosedCandleRow
from strategy_lab.market_data import Candle


@dataclass(frozen=True)
class Plan:
    symbol: str = "INJUSDT"
    side: str = "short"
    entry_time: datetime = datetime(2026, 1, 1, 0, 0)
    exit_time: datetime = datetime(2026, 1, 1, 8, 0)
    entry: float = 10.0
    stop: float = 10.16
    target: float = 9.744
    target_rr: float = 1.6
    setup_type: str = "pullback"
    trend_context: str = "trend"
    volatility_regime: str = "normal"
    structure_type: str = "trend_pullback"


def write_generated(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "symbol": "INJUSDT",
        "side": "short",
        "entry_time": "2025-12-01T00:00:00",
        "exit_time": "2025-12-01T04:00:00",
        "entry": 10.0,
        "stop": 10.16,
        "exit": 9.744,
        "r_mult": 1.6,
        "setup_type": "pullback",
        "trend_context": "trend",
        "volatility_regime": "normal",
        "structure_type": "trend_pullback",
        "exit_reason": "take_profit",
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["SMOKE_RUNTIME_DIR"] = str(root / "runtime")
        os.environ["SMOKE_DB_PATH"] = str(root / "runtime" / "test.sqlite3")
        os.environ["SMOKE_AUTO_SCAN"] = "false"
        os.environ["SMOKE_AUTO_BOOTSTRAP_HISTORY"] = "true"
        os.environ["SMOKE_SYMBOLS_FILE"] = str(root / "missing.txt")
        os.environ["SMOKE_SYMBOLS"] = "INJUSDT"

        import scripts.smoke_control_server as base
        import scripts.smoke_control_server_v2 as hardening

        importlib.reload(base)
        importlib.reload(hardening)
        hardening.apply_patches()
        base.init_schema()

        # Prove bootstrap uses generated_trades.csv (all candidates), not only
        # pipeline_allowed_trades.csv.
        base.STORE.all_candles = lambda *_args, **_kwargs: [
            Candle("INJUSDT", datetime(2025, 1, 1) + timedelta(minutes=15 * idx), 10, 11, 9, 10, 100)
            for idx in range(300)
        ]

        def fake_pipeline(_candles, out_dir, *_args, **_kwargs):
            write_generated(Path(out_dir) / "generated_trades.csv")
            (Path(out_dir) / "pipeline_allowed_trades.csv").write_text("", encoding="utf-8")

        base.run_end_to_end_pipeline = fake_pipeline
        assert base.bootstrap_history_if_needed(["INJUSDT"]) == 1
        assert len(base.historical_trades()) == 1

        # Prove every live raw candidate gets a shadow outcome and then becomes
        # available to causal adaptive history after it closes.
        plan = Plan()
        assert hardening.open_shadow_trade(plan)
        base.STORE.upsert([
            ClosedCandleRow(
                symbol="INJUSDT",
                interval="15m",
                open_time_ms=int(datetime(2026, 1, 1, 0, 15).timestamp() * 1000),
                close_time_ms=int(datetime(2026, 1, 1, 0, 30).timestamp() * 1000) - 1,
                open=10.0,
                high=10.1,
                low=9.70,
                close=9.80,
                volume=100,
            )
        ])
        assert hardening.monitor_shadow_trades() == 1
        history = base.historical_trades()
        assert len(history) == 2
        assert any(item.source == "live_shadow" and round(item.r_mult, 4) == 1.6 for item in history)
    print("SHADOW HISTORY SMOKE TEST OK")


if __name__ == "__main__":
    main()
