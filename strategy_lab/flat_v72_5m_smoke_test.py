#!/usr/bin/env python3
"""Fast invariants for the causal Flat v7.2 5m soft overlay."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.flat_v72 import FlatV72Config, generate_flat_v72_plans
from strategy_lab.flat_v72_5m import SPECS, build_overlay_rows, resample_complete_5m_to_15m
from strategy_lab.market_data import Candle


def source_5m() -> list[Candle]:
    start = datetime(2025, 1, 1)
    rows: list[Candle] = []
    previous = 100.0
    for index in range(3900):
        cycle = index % 240
        drift = index * 0.0008
        base = 100.0 + drift + (cycle - 120) * 0.008
        shock = cycle in {15, 16, 17}
        low = base - (1.8 if shock else 0.18)
        high = base + 0.22
        close = base + (0.16 if shock else 0.03)
        volume = 4500.0 if shock else 1000.0
        rows.append(
            Candle(
                "TESTUSDT",
                start + timedelta(minutes=5 * index),
                previous,
                high,
                low,
                close,
                volume,
            )
        )
        previous = close
    return rows


def main() -> None:
    micro = source_5m()
    base = resample_complete_5m_to_15m(micro)
    assert len(base) == len(micro) // 3
    cfg = FlatV72Config(
        name="FLAT_5M_SMOKE",
        use_60m_trend_filter=False,
        use_15m_ema200_filter=False,
        min_range_width_pct=0.1,
        atr_touch_buffer=5.0,
        center_ban_low=1.0,
        dynamic_volume=False,
        fixed_volume_multiplier=1.1,
        minimum_rr=0.8,
        fixed_target_rr=1.0,
        use_structural_target=False,
        max_holding_bars=8,
    )
    plans, _summary = generate_flat_v72_plans(base, cfg)
    assert plans, "expected deterministic base plans"
    baseline_count = None
    for spec in SPECS:
        rows, diagnostics = build_overlay_rows(plans, micro, spec)
        assert rows, f"expected rows for {spec.name}"
        assert diagnostics["generated_trades"] == len(rows)
        assert all(float(row["risk_multiplier"]) > 0 for row in rows)
        assert all(str(row["micro_state"]) in {"supportive", "neutral", "adverse", "missing"} for row in rows)
        if baseline_count is None:
            baseline_count = len(rows)
        assert len(rows) == baseline_count, "soft overlay must not remove trades"
    print("Flat v7.2 5m soft overlay smoke test passed")


if __name__ == "__main__":
    main()
