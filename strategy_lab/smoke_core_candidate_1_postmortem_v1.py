#!/usr/bin/env python3
"""Post-mortem diagnostics for the one authoritative Candidate 1 development test.

This is diagnostic-only. It consumes the frozen artifacts produced by run
31130707800, reproduces the exact 909 portfolio-accepted closed trades, verifies
that the authoritative top-line metrics match, then reports where losses came
from. It does not modify recognition, execution, costs, risk, portfolio rules,
or any frozen gate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable, Mapping, Sequence

from strategy_lab.economics_risk_portfolio_v1 import CostModel
from strategy_lab.outcome_blind_recognition_v1 import dedupe_global, is_counted
import strategy_lab.p7_full_recognition_runner_v1 as runner
import strategy_lab.p7_partitioned_recognition_v1 as partition
from strategy_lab.smoke_core_development_profitability_v1 import (
    CANDIDATE_ID,
    EXPECTED_RECOGNIZED,
    TEST_ID,
    CapturedPlan,
    _obs_key,
    _obs_from_dict,
    _resolve_plan,
    _simulate,
)

AUTHORITATIVE_RUN_ID = 31130707800
POSTMORTEM_ID = "SMOKE_CORE_CANDIDATE_1_POSTMORTEM_V1"
EXPECTED_CLOSED = 909
EXPECTED_PF = 0.624302699
EXPECTED_AVG_RETURN = -0.1636906304
EXPECTED_DD = 81.8723896881


def _round(value: float | None, digits: int = 10) -> float | None:
    return None if value is None else round(float(value), digits)


def _pf(rows: Sequence[Mapping[str, Any]]) -> float | None:
    gains = sum(max(0.0, float(row["net_pnl"])) for row in rows)
    losses = -sum(min(0.0, float(row["net_pnl"])) for row in rows)
    if losses == 0:
        return None if gains == 0 else 999999.0
    return gains / losses


def _group_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0, "target": 0, "stop": 0, "forced_end": 0,
            "target_rate_pct": 0.0, "stop_rate_pct": 0.0,
            "net_pnl": 0.0, "profit_factor": None,
            "average_net_move_pct": 0.0, "median_net_move_pct": 0.0,
            "average_upstream_score": 0.0,
            "average_hold_minutes": 0.0,
            "average_stop_distance_pct": 0.0,
            "average_target_distance_pct": 0.0,
            "average_raw_rr": 0.0,
        }
    targets = sum(row["outcome"] == "TARGET" for row in rows)
    stops = sum(row["outcome"] == "STOP" for row in rows)
    forced = sum(row["outcome"] == "FORCED_END" for row in rows)
    holds: list[float] = []
    stop_distances: list[float] = []
    target_distances: list[float] = []
    raw_rrs: list[float] = []
    for row in rows:
        start = datetime.fromisoformat(str(row["entry_time"]))
        end = datetime.fromisoformat(str(row["exit_time"]))
        holds.append((end - start).total_seconds() / 60.0)
        entry = float(row["entry_price"])
        stop_dist = abs(entry - float(row["stop_price"])) / entry * 100.0
        target_dist = abs(float(row["target_price"]) - entry) / entry * 100.0
        stop_distances.append(stop_dist)
        target_distances.append(target_dist)
        raw_rrs.append(target_dist / stop_dist if stop_dist > 0 else 0.0)
    net_moves = [float(row["net_move_pct"]) for row in rows]
    return {
        "count": len(rows),
        "target": targets,
        "stop": stops,
        "forced_end": forced,
        "target_rate_pct": _round(targets / len(rows) * 100.0),
        "stop_rate_pct": _round(stops / len(rows) * 100.0),
        "net_pnl": _round(sum(float(row["net_pnl"]) for row in rows)),
        "profit_factor": _round(_pf(rows)),
        "average_net_move_pct": _round(mean(net_moves)),
        "median_net_move_pct": _round(median(net_moves)),
        "average_upstream_score": _round(mean(float(row["upstream_score"]) for row in rows)),
        "average_hold_minutes": _round(mean(holds)),
        "average_stop_distance_pct": _round(mean(stop_distances)),
        "average_target_distance_pct": _round(mean(target_distances)),
        "average_raw_rr": _round(mean(raw_rrs)),
    }


def _group(rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], str]) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return {name: _group_metrics(sample) for name, sample in sorted(groups.items())}


def _score_bucket(score: float) -> str:
    if score < 70: return "<70"
    if score < 75: return "70-74.999"
    if score < 80: return "75-79.999"
    if score < 85: return "80-84.999"
    if score < 90: return "85-89.999"
    return ">=90"


def _rr_bucket(row: Mapping[str, Any]) -> str:
    entry = float(row["entry_price"])
    risk = abs(entry - float(row["stop_price"]))
    reward = abs(float(row["target_price"]) - entry)
    rr = reward / risk if risk > 0 else 0.0
    if rr < 1.5: return "<1.50"
    if rr < 1.75: return "1.50-1.749"
    if rr < 2.0: return "1.75-1.999"
    if rr < 2.5: return "2.00-2.499"
    return ">=2.50"


def _stop_bucket(row: Mapping[str, Any]) -> str:
    entry = float(row["entry_price"])
    distance = abs(entry - float(row["stop_price"])) / entry * 100.0
    if distance < 0.5: return "<0.50%"
    if distance < 1.0: return "0.50-0.99%"
    if distance < 1.5: return "1.00-1.49%"
    if distance < 2.0: return "1.50-1.99%"
    return ">=2.00%"


def _hold_bucket(row: Mapping[str, Any]) -> str:
    start = datetime.fromisoformat(str(row["entry_time"]))
    end = datetime.fromisoformat(str(row["exit_time"]))
    minutes = (end - start).total_seconds() / 60.0
    if minutes <= 30: return "<=30m"
    if minutes <= 120: return "31-120m"
    if minutes <= 360: return "121-360m"
    if minutes <= 1440: return "361-1440m"
    return ">1440m"


def _rank_harmful(groups: Mapping[str, Mapping[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    ranked = sorted(groups.items(), key=lambda item: float(item[1]["net_pnl"]))
    return [{"group": name, **metrics} for name, metrics in ranked[:limit]]


def build_postmortem(partition_paths: Iterable[Path], data_root: Path, authoritative_report: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(partition_paths)]
    if len(payloads) != 50:
        raise ValueError(f"expected 50 authoritative partitions, got {len(payloads)}")
    if {payload["test_id"] for payload in payloads} != {TEST_ID}:
        raise ValueError("partition test id mismatch")

    plans = [CapturedPlan(**plan) for payload in payloads for plan in payload["plans"]]
    observations = [_obs_from_dict(plan.observation) for plan in plans]
    deduped, duplicates = dedupe_global(observations)
    counted = [row for row in deduped if is_counted(row)]
    if len(counted) != EXPECTED_RECOGNIZED or duplicates != 0:
        raise AssertionError((len(counted), duplicates))

    plan_map = {_obs_key(plan.observation): plan for plan in plans}
    counted_plans = [plan_map[_obs_key(partition._observation_to_dict(row))] for row in counted]
    _, candles_by_symbol = runner.load_locked_dataset(data_root)
    resolved = [
        _resolve_plan(
            plan,
            candles_by_symbol[str(plan.observation["symbol"])],
            [c.time for c in candles_by_symbol[str(plan.observation["symbol"]) ]],
            CostModel(),
        )
        for plan in counted_plans
    ]
    closed, metrics = _simulate(sorted(resolved, key=lambda t: (t.entry_time, -t.upstream_score, t.fingerprint)))

    authoritative = json.loads(authoritative_report.read_text(encoding="utf-8"))
    if authoritative["status"] != "FAIL" or authoritative["decision"] != "CLOSE_CANDIDATE_1_WITHOUT_TUNING":
        raise AssertionError("authoritative verdict mismatch")
    checks = {
        "closed_trades": len(closed) == EXPECTED_CLOSED == authoritative["metrics"]["closed_trades"],
        "profit_factor": abs(float(metrics["pooled_profit_factor"]) - EXPECTED_PF) < 1e-9,
        "average_return": abs(float(metrics["average_trade_return_after_costs_pct"]) - EXPECTED_AVG_RETURN) < 1e-9,
        "max_drawdown": abs(float(metrics["max_drawdown_pct"]) - EXPECTED_DD) < 1e-9,
        "ending_equity": abs(float(metrics["ending_equity"]) - float(authoritative["metrics"]["ending_equity"])) < 1e-9,
    }
    if not all(checks.values()):
        raise AssertionError({"reproduction_checks": checks, "metrics": metrics})

    by_symbol = _group(closed, lambda row: str(row["symbol"]))
    by_direction = _group(closed, lambda row: str(row["direction"]))
    by_family = _group(closed, lambda row: str(row["family"]))
    by_fold = _group(closed, lambda row: str(row["fold"]))
    by_symbol_direction = _group(closed, lambda row: f"{row['symbol']}|{row['direction']}")
    by_family_direction = _group(closed, lambda row: f"{row['family']}|{row['direction']}")
    by_score = _group(closed, lambda row: _score_bucket(float(row["upstream_score"])))
    by_rr = _group(closed, _rr_bucket)
    by_stop = _group(closed, _stop_bucket)
    by_hold = _group(closed, _hold_bucket)

    profitable_atomic = []
    for source_name, groups in (("symbol_direction", by_symbol_direction), ("family_direction", by_family_direction)):
        for name, stats in groups.items():
            if stats["count"] >= 20 and float(stats["net_pnl"]) > 0 and (stats["profit_factor"] or 0) > 1.0:
                profitable_atomic.append({"source": source_name, "group": name, **stats})

    result = {
        "postmortem_id": POSTMORTEM_ID,
        "source": {
            "authoritative_run_id": AUTHORITATIVE_RUN_ID,
            "test_id": TEST_ID,
            "candidate_id": CANDIDATE_ID,
            "verdict": authoritative["status"],
            "decision": authoritative["decision"],
            "diagnostic_only": True,
            "not_a_second_development_test": True,
        },
        "reproduction_checks": checks,
        "authoritative_metrics": authoritative["metrics"],
        "breakdowns": {
            "by_symbol": by_symbol,
            "by_direction": by_direction,
            "by_family": by_family,
            "by_fold": by_fold,
            "by_symbol_direction": by_symbol_direction,
            "by_family_direction": by_family_direction,
            "by_upstream_score_bucket": by_score,
            "by_raw_rr_bucket": by_rr,
            "by_stop_distance_bucket": by_stop,
            "by_hold_time_bucket": by_hold,
        },
        "largest_loss_groups": {
            "symbol_direction": _rank_harmful(by_symbol_direction),
            "family_direction": _rank_harmful(by_family_direction),
            "fold": _rank_harmful(by_fold, 10),
            "score_bucket": _rank_harmful(by_score, 10),
        },
        "profitable_atomic_groups_min_20_trades": profitable_atomic,
        "guardrail": (
            "These are exploratory diagnostics from already-seen development data. "
            "They may generate Candidate 2 hypotheses, but no threshold, weight, family, "
            "symbol, direction, stop, target, cost, risk, or portfolio change may be "
            "validated on this same dataset as a new authoritative profitability test."
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--authoritative-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_postmortem(
        args.input_dir.rglob("profitability_partition_*.json"),
        args.data_root,
        args.authoritative_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "postmortem_id": POSTMORTEM_ID,
        "reproduction_checks": result["reproduction_checks"],
        "profitable_atomic_groups": len(result["profitable_atomic_groups_min_20_trades"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
