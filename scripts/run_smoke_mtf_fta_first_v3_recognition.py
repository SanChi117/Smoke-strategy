#!/usr/bin/env python3
"""Run an outcome-blind FTA-first V3 recognition scan for one symbol/side."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_fta_first_entry_v3 import (
    MtfFtaFirstEntryModelV3,
    independent_fingerprint,
    plan_to_no_pnl_dict,
)
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl",
    "future_return",
    "trade_outcome",
    "tp_result",
    "sl_result",
    "mfe",
    "mae",
    "win_rate",
    "profit_factor",
    "net_return",
    "drawdown",
    "exit_time",
    "exit_price",
    "exit_reason",
    "gross_return",
    "funding_return",
)


def assert_outcome_blind(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(raw_key).lower()).strip("_")
            for fragment in FORBIDDEN_KEY_FRAGMENTS:
                if fragment in key:
                    raise AssertionError(f"forbidden outcome field at {path}.{raw_key}: {fragment}")
            assert_outcome_blind(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_outcome_blind(child, f"{path}[{index}]")


def scan(
    candles,
    *,
    symbol: str,
    side: str,
    scan_start: datetime,
    scan_end: datetime,
    sample_limit_per_state: int = 4,
) -> dict[str, Any]:
    normalized = symbol.upper()
    symbols = {row.symbol.upper() for row in candles}
    if symbols != {normalized}:
        raise ValueError(f"runner requires exactly {normalized}; got {sorted(symbols)}")
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")

    engine = MtfDealingRangeEngine(candles)
    runtime = install_fast_runtime(engine)
    model = MtfFtaFirstEntryModelV3(engine)

    state_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    target_timeframe_counts: Counter[str] = Counter()
    stop_source_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    independent: dict[str, dict[str, Any]] = {}
    allowed_snapshots = 0
    evaluated = 0

    for bar in engine.bars["15m"]:
        if bar.symbol != normalized or not (scan_start <= bar.open_time < scan_end):
            continue
        evaluated += 1
        plan = model.evaluate(normalized, bar.open_time, side)
        state_counts[plan.state.value] += 1
        reason_counts.update(plan.reasons)
        if plan.route is not None:
            route_counts[plan.route.name] += 1
        if plan.external_fta is not None:
            target_timeframe_counts[plan.external_fta.timeframe] += 1
        if plan.stop_selection is not None:
            stop_source_counts[f"{plan.stop_selection.timeframe}:{plan.stop_selection.source}"] += 1

        record = plan_to_no_pnl_dict(plan)
        if len(samples[plan.state.value]) < sample_limit_per_state:
            samples[plan.state.value].append(record)

        if not plan.allowed:
            continue
        allowed_snapshots += 1
        fingerprint = independent_fingerprint(plan)
        if fingerprint is None:
            raise AssertionError("allowed V3 plan has no independent fingerprint")
        independent.setdefault(fingerprint, record)

    payload: dict[str, Any] = {
        "study_id": "SMOKE_MTF_FTA_FIRST_V3_RECOGNITION_V1",
        "mode": "OUTCOME_BLIND_RECOGNITION",
        "candidate_id": "SMOKE_MTF_FTA_FIRST_V3_FROZEN_CANDIDATE_1",
        "symbol": normalized,
        "side": side,
        "scan_start": scan_start.isoformat(),
        "scan_end": scan_end.isoformat(),
        "evaluated_15m_snapshots": evaluated,
        "state_counts": dict(sorted(state_counts.items())),
        "reason_counts": dict(reason_counts.most_common()),
        "route_counts": dict(sorted(route_counts.items())),
        "target_timeframe_counts": dict(sorted(target_timeframe_counts.items())),
        "stop_source_counts": dict(sorted(stop_source_counts.items())),
        "allowed_snapshots": allowed_snapshots,
        "independent_entry_ready_count": len(independent),
        "duplicate_allowed_snapshots": allowed_snapshots - len(independent),
        "independent_entry_ready": list(independent.values()),
        "state_samples": dict(sorted(samples.items())),
        "runtime": runtime.stats(),
        "contract": {
            "closed_candles_only": True,
            "future_outcomes_excluded": True,
            "profitability_metrics_excluded": True,
            "minimum_independent_cases_before_profitability": 60,
        },
    }
    assert_outcome_blind(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=("long", "short"))
    parser.add_argument("--scan-start", required=True)
    parser.add_argument("--scan-end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    payload = scan(
        candles,
        symbol=args.symbol,
        side=args.side,
        scan_start=parse_dt(args.scan_start),
        scan_end=parse_dt(args.scan_end),
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"symbol={payload['symbol']} side={payload['side']} "
        f"evaluated={payload['evaluated_15m_snapshots']} "
        f"independent_entry_ready={payload['independent_entry_ready_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
