#!/usr/bin/env python3
from strategy_lab.research_metrics import aggregate_oos, pnl_totals


def main() -> int:
    a = pnl_totals([{"event": "CLOSE", "net_pnl": 10}, {"event": "CLOSE", "net_pnl": 5}])
    b = pnl_totals([{"event": "CLOSE", "net_pnl": -10}])
    rows = [
        {"status": "OK", "ret_pct": 1, "max_dd_pct": 1, "executed_trades": 2, **a},
        {"status": "OK", "ret_pct": -1, "max_dd_pct": 2, "executed_trades": 1, **b},
    ]
    result = aggregate_oos("TEST", rows)
    assert result["pooled_pf"] == 1.5
    assert result["net_pnl"] == 5.0
    assert result["verdict"] == "WATCH_TOO_SPARSE"
    print("research_metrics_smoke_test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
