#!/usr/bin/env python3
"""Fast invariants for the causal Flat v7.2 research port."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.flat_v72 import FlatV72Config, generate_flat_v72_plans, simulate_flat_v72_rows
from strategy_lab.market_data import Candle


def candles() -> list[Candle]:
    start = datetime(2025, 1, 1)
    out: list[Candle] = []
    price = 100.0
    for index in range(1300):
        cycle = index % 80
        drift = index * 0.002
        base = 100.0 + drift + (cycle - 40) * 0.025
        low = base - (2.5 if cycle == 5 else 0.35)
        high = base + 0.45
        close = base + (0.20 if cycle == 5 else 0.05)
        volume = 5000.0 if cycle == 5 else 1000.0
        out.append(Candle("TESTUSDT", start + timedelta(minutes=15 * index), price, high, low, close, volume))
        price = close
    return out


def main() -> None:
    cfg = FlatV72Config(
        name="SMOKE_TEST",
        use_60m_trend_filter=False,
        use_15m_ema200_filter=False,
        min_range_width_pct=0.1,
        atr_touch_buffer=5.0,
        center_ban_low=1.0,
        dynamic_volume=False,
        fixed_volume_multiplier=1.2,
        minimum_rr=0.8,
        fixed_target_rr=1.0,
        use_structural_target=False,
        max_holding_bars=8,
    )
    source = candles()
    plans, summary = generate_flat_v72_plans(source, cfg)
    assert summary["plans"] == len(plans)
    assert plans, "expected at least one deterministic Flat plan"
    assert all(plan.entry_time > source[0].time for plan in plans)
    rows = simulate_flat_v72_rows(plans, source)
    assert rows, "expected simulated rows"
    assert all(row["setup_type"] == "flat_v72" for row in rows)
    assert all(float(row["stop"]) < float(row["entry"]) < float(row["target"]) for row in rows)
    assert all(str(row["exit_time"]) > str(row["entry_time"]) for row in rows)
    print("Flat v7.2 causal smoke test passed")


if __name__ == "__main__":
    main()
