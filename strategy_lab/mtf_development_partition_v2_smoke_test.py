#!/usr/bin/env python3
"""Regression test for execution-only long/short development partitioning."""

from scripts.aggregate_smoke_mtf_v2_development import expected_partition_keys


def main() -> int:
    keys = expected_partition_keys()
    assert len(keys) == 100
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT"):
        for fold in range(10):
            assert (symbol, fold, "long") in keys
            assert (symbol, fold, "short") in keys
    assert len({(symbol, fold) for symbol, fold, _side in keys}) == 50
    assert {side for _symbol, _fold, side in keys} == {"long", "short"}
    print("SMOKE MTF V2 development side partition: 100 exact parts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
