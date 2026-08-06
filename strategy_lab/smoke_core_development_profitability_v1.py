#!/usr/bin/env python3
"""One preregistered development-profitability test for frozen SMOKE CORE Candidate 1.

The adapter replays the exact frozen P7/P8 recognition path and captures entry,
structural stop and preselected target at the existing observation boundary. It
does not create, delete or reclassify recognition rows. Outcomes are read only
after all 50 symbol-fold partitions have been reconstructed and globally
fingerprint-deduplicated.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from strategy_lab.economics_risk_portfolio_v1 import (
    AccountState,
    AdmissionDecision,
    CostModel,
    ExecutionCandidate,
    RiskLimits,
    Side,
    evaluate_candidate,
    rank_simultaneous_candidates,
)
from strategy_lab.market_data import Candle
from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_DIRECTIONS,
    ALLOWED_SYMBOLS,
    RecognitionObservation,
    dedupe_global,
    is_counted,
)
import strategy_lab.p7_full_recognition_runner_v1 as runner
import strategy_lab.p7_partition_shards_v1 as shards
import strategy_lab.p7_partitioned_recognition_v1 as partition

TEST_ID = "SMOKE_CORE_CANDIDATE_1_DEVELOPMENT_PROFITABILITY_FIXED_V1"
CANDIDATE_ID = "SMOKE_CORE_1_0_CANDIDATE_1"
FROZEN_P8_SHA = "eef6bf319f53e4434d5f99bf54bc7f78c1b41f75"
FROZEN_MANIFEST_SHA = "8fa00da7f22c70ddd48208a3cdcf678d540f29738bbff6ef9978f72477e4b429"
EXPECTED_RECOGNIZED = 2620
REPORT_PATH = Path("research_outputs/smoke_core_candidate_1_development_profitability_report_v1.json")


@dataclass(frozen=True)
class CapturedPlan:
    observation: Mapping[str, Any]
    entry_price: float
    stop_price: float
    target_price: float
    entry_start: str
    upstream_score: float


@dataclass(frozen=True)
class ResolvedPlan:
    fingerprint: str
    symbol: str
    direction: str
    fold: int
    family: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    outcome: str
    gross_move_pct: float
    net_move_pct: float
    upstream_score: float


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _obs_from_dict(payload: Mapping[str, Any]) -> RecognitionObservation:
    return partition._observation_from_dict(dict(payload))


def _obs_key(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(payload["fingerprint"]), str(payload["timestamp"]), str(payload["symbol"]),
        str(payload["direction"]), int(payload["fold"]),
    )


def _capture_install(storage: list[CapturedPlan]) -> None:
    original = runner._build_observation

    def capture(symbol, fold, timestamp, spec, view, structure, entry_price, target, target_level, bars_15m, evidence_map):
        observation = original(
            symbol, fold, timestamp, spec, view, structure, entry_price,
            target, target_level, bars_15m, evidence_map,
        )
        if observation is None:
            return None
        costs = CostModel()
        buffer_fraction = costs.cost_buffer_pct / 100.0
        stop_price = (
            structure.protected_swing * (1.0 - buffer_fraction)
            if observation.direction == "LONG"
            else structure.protected_swing * (1.0 + buffer_fraction)
        )
        base_evidence = runner._base_family_evidence(spec, view, structure, target_level, evidence_map)
        preliminary_input = runner.FusionInput(
            symbol=symbol,
            side=observation.direction,
            family=spec.family,
            evaluated_at=timestamp,
            target_level_id=target_level.level_id,
            poi_id=spec.poi.poi_id,
            anchor_id=spec.anchor.anchor_id,
            structure_id=structure.structure_id,
            protected_swing_id=runner._stable_id("protected", structure.structure_id, round(structure.protected_swing, 12)),
            poi_lifecycle_id=f"{spec.poi.poi_id}:{spec.poi.state.value}:{spec.poi.test_count}",
            discovered=True, armed=True, reaction_detected=True, structure_confirmed=True,
            economics_valid=False, risk_valid=False, hard_blocks=(),
            critical_conflicts=tuple(view.conflicts + structure.conflicts),
        )
        preliminary = runner.fuse_scenario(preliminary_input, base_evidence)
        payload = partition._observation_to_dict(observation)
        storage.append(CapturedPlan(
            observation=payload,
            entry_price=float(entry_price),
            stop_price=float(stop_price),
            target_price=float(target.price),
            entry_start=(observation.timestamp - timedelta(minutes=15)).isoformat(),
            upstream_score=float(preliminary.scenario.total_score_0_100),
        ))
        return observation

    runner._build_observation = capture


def scan_shard(symbol: str, fold: int, shard_index: int, shard_count: int, output: Path) -> dict[str, Any]:
    captured: list[CapturedPlan] = []
    _capture_install(captured)
    temporary = output.with_suffix(".recognition.json")
    payload = shards.scan_shard(symbol, fold, shard_index, shard_count, temporary)
    recognition_keys = {_obs_key(row) for row in payload["observations"]}
    plans = [plan for plan in captured if _obs_key(plan.observation) in recognition_keys]
    if len(plans) != len(payload["observations"]):
        raise AssertionError((len(plans), len(payload["observations"])))
    result = {
        "test_id": TEST_ID,
        "candidate_id": CANDIDATE_ID,
        "recognition_id": runner.RECOGNITION_ID,
        "symbol": symbol,
        "fold": fold,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "data_manifest_sha256": payload["data_manifest_sha256"],
        "diagnostics": payload["diagnostics"],
        "plans": [_jsonable(plan) for plan in plans],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    temporary.unlink(missing_ok=True)
    return result


def merge_shards(paths: Iterable[Path], symbol: str, fold: int, output: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text()) for path in sorted(paths)]
    if not payloads:
        raise ValueError("no profitability shards")
    count = int(payloads[0]["shard_count"])
    if len(payloads) != count or {int(p["shard_index"]) for p in payloads} != set(range(count)):
        raise ValueError("profitability shard coverage mismatch")
    if {p["symbol"] for p in payloads} != {symbol} or {int(p["fold"]) for p in payloads} != {fold}:
        raise ValueError("profitability shard symbol/fold mismatch")
    if len({p["data_manifest_sha256"] for p in payloads}) != 1:
        raise ValueError("profitability shard manifest mismatch")
    result = {
        "test_id": TEST_ID,
        "candidate_id": CANDIDATE_ID,
        "recognition_id": runner.RECOGNITION_ID,
        "symbol": symbol,
        "fold": fold,
        "data_manifest_sha256": payloads[0]["data_manifest_sha256"],
        "plans": [plan for p in sorted(payloads, key=lambda x: int(x["shard_index"])) for plan in p["plans"]],
        "execution_shards": count,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _resolve_plan(plan: CapturedPlan, candles: Sequence[Candle], times: Sequence[datetime], costs: CostModel) -> ResolvedPlan:
    obs = plan.observation
    direction = str(obs["direction"])
    start = datetime.fromisoformat(plan.entry_start)
    selected = [row for row in candles if row.time >= start]
    if not selected:
        raise ValueError(f"no outcome bars for {obs['fingerprint']}")
    outcome = "FORCED_END"
    exit_row = selected[-1]
    exit_price = float(exit_row.close)
    for row in selected:
        stop_hit = row.low <= plan.stop_price if direction == "LONG" else row.high >= plan.stop_price
        target_hit = row.high >= plan.target_price if direction == "LONG" else row.low <= plan.target_price
        if stop_hit:
            outcome, exit_row, exit_price = "STOP", row, plan.stop_price
            break
        if target_hit:
            outcome, exit_row, exit_price = "TARGET", row, plan.target_price
            break
    gross = (
        (exit_price - plan.entry_price) / plan.entry_price * 100.0
        if direction == "LONG"
        else (plan.entry_price - exit_price) / plan.entry_price * 100.0
    )
    net = gross - costs.total_cost_pct
    return ResolvedPlan(
        fingerprint=str(obs["fingerprint"]), symbol=str(obs["symbol"]), direction=direction,
        fold=int(obs["fold"]), family=str(obs["family"]), entry_time=start,
        exit_time=exit_row.time, entry_price=plan.entry_price, exit_price=float(exit_price),
        stop_price=plan.stop_price, target_price=plan.target_price, outcome=outcome,
        gross_move_pct=round(gross, 10), net_move_pct=round(net, 10),
        upstream_score=plan.upstream_score,
    )


def _candidate(trade: ResolvedPlan) -> ExecutionCandidate:
    stop_pct = abs(trade.entry_price - trade.stop_price) / trade.entry_price * 100.0
    return ExecutionCandidate(
        candidate_id=trade.fingerprint,
        symbol=trade.symbol,
        side=Side(trade.direction),
        evaluated_at=trade.entry_time.isoformat(),
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        target_price=trade.target_price,
        atr_floor_pct=0.0,
        liquidity_buffer_pct=0.0,
        upstream_score=trade.upstream_score,
        dependency_ids=(trade.fingerprint,),
        dependencies_causal=True,
        leverage=20.0,
        margin_mode="isolated",
        liquidation_price=trade.entry_price * (0.95 if trade.direction == "LONG" else 1.05),
        correlation_cluster="CRYPTO_MARKET_BETA",
    )


def _simulate(trades: Sequence[ResolvedPlan]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    costs = CostModel(); limits = RiskLimits()
    equity = 10000.0; peak = equity; max_dd = 0.0
    open_positions: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    fold_pnl = {fold: 0.0 for fold in range(10)}

    def close_until(timestamp: datetime) -> None:
        nonlocal equity, peak, max_dd, open_positions
        due = sorted((p for p in open_positions if p["trade"].exit_time <= timestamp), key=lambda p: (p["trade"].exit_time, p["trade"].fingerprint))
        for position in due:
            trade = position["trade"]
            pnl = position["notional"] * trade.net_move_pct / 100.0
            equity += pnl
            fold_pnl[trade.fold] += pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100.0 if peak else 0.0)
            closed.append({**_jsonable(trade), "notional": round(position["notional"], 10), "net_pnl": round(pnl, 10), "equity_after": round(equity, 10)})
            open_positions.remove(position)

    grouped: dict[datetime, list[ResolvedPlan]] = {}
    for trade in trades:
        grouped.setdefault(trade.entry_time, []).append(trade)
    for timestamp in sorted(grouped):
        close_until(timestamp)
        open_risk = len(open_positions) * limits.risk_per_position_pct
        used_margin = sum(p["margin_pct"] for p in open_positions)
        total_notional = sum(p["notional_multiple"] for p in open_positions)
        account = AccountState(equity=equity, open_risk_pct=open_risk, used_margin_pct=used_margin, total_notional_multiple=total_notional)
        candidates = [_candidate(t) for t in grouped[timestamp]]
        evaluations = [evaluate_candidate(c, account, costs, limits) for c in candidates]
        scores = {c.candidate_id: c.upstream_score for c in candidates}
        selected = rank_simultaneous_candidates(evaluations, account, limits, scores)
        trade_map = {t.fingerprint: t for t in grouped[timestamp]}
        for result in selected:
            if result.decision not in {AdmissionDecision.PASS, AdmissionDecision.CONDITIONAL_PASS}:
                continue
            trade = trade_map[result.candidate_id]
            open_positions.append({
                "trade": trade,
                "notional": result.position.notional,
                "margin_pct": result.position.margin_pct_equity,
                "notional_multiple": result.position.notional_multiple_equity,
            })
    close_until(datetime.max.replace(tzinfo=trades[0].entry_time.tzinfo) if trades else datetime.max)
    gains = sum(max(0.0, row["net_pnl"]) for row in closed)
    losses = -sum(min(0.0, row["net_pnl"]) for row in closed)
    pf = gains / losses if losses > 0 else (float("inf") if gains > 0 else 0.0)
    avg_return = sum(row["net_pnl"] / max(1e-12, row["equity_after"] - row["net_pnl"]) * 100.0 for row in closed) / len(closed) if closed else 0.0
    metrics = {
        "closed_trades": len(closed),
        "pooled_profit_factor": round(pf, 10) if pf != float("inf") else "INF",
        "average_trade_return_after_costs_pct": round(avg_return, 10),
        "positive_folds": sum(value > 0 for value in fold_pnl.values()),
        "fold_net_pnl": {str(k): round(v, 10) for k, v in fold_pnl.items()},
        "max_drawdown_pct": round(max_dd, 10),
        "starting_equity": 10000.0,
        "ending_equity": round(equity, 10),
    }
    return closed, metrics


def aggregate(partition_paths: Iterable[Path], data_root: Path, output: Path = REPORT_PATH) -> dict[str, Any]:
    payloads = [json.loads(path.read_text()) for path in sorted(partition_paths)]
    expected_keys = {(s, f) for s in ALLOWED_SYMBOLS for f in range(10)}
    if len(payloads) != 50 or {(p["symbol"], int(p["fold"])) for p in payloads} != expected_keys:
        raise ValueError("expected exact 50 symbol-fold profitability partitions")
    if {p["test_id"] for p in payloads} != {TEST_ID} or len({p["data_manifest_sha256"] for p in payloads}) != 1:
        raise ValueError("profitability partition contract mismatch")
    plans = [CapturedPlan(**plan) for payload in payloads for plan in payload["plans"]]
    observations = [_obs_from_dict(plan.observation) for plan in plans]
    deduped, duplicate_rows = dedupe_global(observations)
    counted = [row for row in deduped if is_counted(row)]
    if len(counted) != EXPECTED_RECOGNIZED:
        raise AssertionError(f"frozen recognition mismatch: {len(counted)} != {EXPECTED_RECOGNIZED}")
    plan_map = {_obs_key(plan.observation): plan for plan in plans}
    counted_plans = [plan_map[_obs_key(partition._observation_to_dict(row))] for row in counted]
    _, candles_by_symbol = runner.load_locked_dataset(data_root)
    resolved = [
        _resolve_plan(plan, candles_by_symbol[str(plan.observation["symbol"])], [c.time for c in candles_by_symbol[str(plan.observation["symbol"])]], CostModel())
        for plan in counted_plans
    ]
    closed, metrics = _simulate(sorted(resolved, key=lambda t: (t.entry_time, -t.upstream_score, t.fingerprint)))
    pf = metrics["pooled_profit_factor"]
    pf_value = float("inf") if pf == "INF" else float(pf)
    gates = {
        "minimum_60_closed_trades": metrics["closed_trades"] >= 60,
        "pooled_pf_at_least_1_20": pf_value >= 1.20,
        "positive_average_trade_return": metrics["average_trade_return_after_costs_pct"] > 0,
        "at_least_6_of_10_positive_folds": metrics["positive_folds"] >= 6,
        "max_drawdown_at_most_8_pct": metrics["max_drawdown_pct"] <= 8.0,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    result = {
        "test_id": TEST_ID,
        "candidate_id": CANDIDATE_ID,
        "status": status,
        "decision": "PREPARE_UNTOUCHED_EXTERNAL_HOLDOUT" if status == "PASS" else "CLOSE_CANDIDATE_1_WITHOUT_TUNING",
        "frozen_basis": {"p8_sha": FROZEN_P8_SHA, "freeze_manifest_sha256": FROZEN_MANIFEST_SHA, "recognized_entry_ready": len(counted)},
        "contract": {"symbols": list(ALLOWED_SYMBOLS), "directions": list(ALLOWED_DIRECTIONS), "fold_count": 10, "global_fingerprint_dedupe": True, "duplicate_rows": duplicate_rows, "stop_first_same_bar": True, "cost_model": asdict(CostModel()), "risk_limits": asdict(RiskLimits())},
        "metrics": metrics,
        "gates": gates,
        "trade_distribution": {
            "by_symbol": {s: sum(row["symbol"] == s for row in closed) for s in ALLOWED_SYMBOLS},
            "by_direction": {d: sum(row["direction"] == d for row in closed) for d in ALLOWED_DIRECTIONS},
            "by_fold": {str(f): sum(int(row["fold"]) == f for row in closed) for f in range(10)},
            "by_outcome": {name: sum(row["outcome"] == name for row in closed) for name in ("TARGET", "STOP", "FORCED_END")},
        },
        "one_test_rule": "AUTHORITATIVE_DEVELOPMENT_TEST_V1",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan-shard")
    scan.add_argument("--symbol", required=True); scan.add_argument("--fold", type=int, required=True)
    scan.add_argument("--shard-index", type=int, required=True); scan.add_argument("--shard-count", type=int, required=True)
    scan.add_argument("--output", type=Path, required=True)
    merge = sub.add_parser("merge-shards")
    merge.add_argument("--input-dir", type=Path, required=True); merge.add_argument("--symbol", required=True)
    merge.add_argument("--fold", type=int, required=True); merge.add_argument("--output", type=Path, required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--input-dir", type=Path, required=True); agg.add_argument("--data-root", type=Path, required=True)
    agg.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    if args.command == "scan-shard":
        scan_shard(args.symbol.upper(), args.fold, args.shard_index, args.shard_count, args.output)
    elif args.command == "merge-shards":
        merge_shards(args.input_dir.rglob(f"profitability_shard_{args.symbol.upper()}_{args.fold}_*.json"), args.symbol.upper(), args.fold, args.output)
    else:
        result = aggregate(args.input_dir.rglob("profitability_partition_*.json"), args.data_root, args.output)
        print(json.dumps({"test_id": TEST_ID, "status": result["status"], "metrics": result["metrics"], "decision": result["decision"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
