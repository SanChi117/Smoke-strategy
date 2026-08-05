#!/usr/bin/env python3
"""Regression tests for the outcome-blind SMOKE MTF funnel audit."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from strategy_lab.mtf_no_pnl_funnel_v1 import (
    STAGES,
    assert_no_outcome_fields,
    contiguous_fold_bounds,
    stage_flags,
    transition_rates,
)


def _plan(**overrides):
    base = {
        "context": SimpleNamespace(long_allowed=True, short_allowed=False),
        "poi": SimpleNamespace(),
        "h1_raid": True,
        "h1_vc": False,
        "vc_zone_test": False,
        "bos": SimpleNamespace(),
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "rr": 2.0,
        "allowed": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def main() -> int:
    flags = stage_flags(_plan(), "long", 1.70)
    assert all(flags[stage] for stage in STAGES)

    blocked = stage_flags(_plan(context=SimpleNamespace(long_allowed=False, short_allowed=False)), "long", 1.70)
    assert blocked["CLOSED_DATA_AVAILABLE"] is True
    assert all(blocked[stage] is False for stage in STAGES[1:])

    no_poi = stage_flags(_plan(poi=None), "long", 1.70)
    assert no_poi["CONTEXT_ALIGNED"] is True
    assert all(no_poi[stage] is False for stage in STAGES[2:])

    weak_rr = stage_flags(_plan(rr=1.20, allowed=False), "long", 1.70)
    assert weak_rr["ACTIVE_FTA_VALID"] is True
    assert weak_rr["RR_GATE_PASSED"] is False
    assert weak_rr["ENTRY_READY"] is False

    missing_stop = stage_flags(_plan(stop=None, allowed=False), "long", 1.70)
    assert missing_stop["NEXT_15M_EXECUTION_ELIGIBLE"] is True
    assert all(missing_stop[stage] is False for stage in STAGES[7:])

    counts = {stage: 100 - index * 5 for index, stage in enumerate(STAGES)}
    rates = transition_rates(counts)
    assert rates["CLOSED_DATA_AVAILABLE->CONTEXT_ALIGNED"]["rate"] == 0.95

    bounds = contiguous_fold_bounds(datetime(2025, 1, 1), datetime(2026, 7, 1), 10)
    assert len(bounds) == 10
    assert bounds[0][0] == datetime(2025, 1, 1)
    assert bounds[-1][1] == datetime(2026, 7, 1)
    assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))

    assert_no_outcome_fields({"windows": 10, "structural_rr": [1.2, 2.0], "outcome_fields_excluded": True})
    try:
        assert_no_outcome_fields({"net_return_fraction": 0.1})
    except AssertionError:
        pass
    else:
        raise AssertionError("net return field was not rejected")

    print("mtf no-PnL funnel smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
