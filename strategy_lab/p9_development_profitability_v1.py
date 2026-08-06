#!/usr/bin/env python3
"""SMOKE CORE 1.0 P9: preregistered development profitability evaluation.

This module observes the frozen P7/P8 Candidate 1 recognition path without
changing it, captures the exact geometry and P5 admission objects already
created by the frozen runner, resolves outcomes on the locked 5m dataset, and
simulates one chronological portfolio under the frozen P5 limits.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import strategy_lab.p7_partitioned_recognition_entrypoint_v1 as _entrypoint  # noqa: F401,E402
import strategy_lab.p7_full_recognition_runner_v1 as runner  # noqa: E402
import strategy_lab.p7_partition_shards_v1 as p7_shards  # noqa: E402
import strategy_lab.p7_partitioned_recognition_v1 as partition  # noqa: E402
from strategy_lab.economics_risk_portfolio_v1 import CostModel, RiskLimits  # noqa: E402
from strategy_lab.outcome_blind_recognition_v1 import RecognitionObservation, dedupe_global, is_counted  # noqa: E402

P9_ID = "SMOKE_CORE_P9_DEVELOPMENT_PROFITABILITY_FIXED_V1"
CANDIDATE_ID = "SMOKE_CORE_1_0_CANDIDATE_1"
P7_RUN_ID = 30899050584
P7_HEAD = "b749be2578251a3b447a78a79009ff3d45cffc57"
P8_RUN_ID = 31004476021
P8_HEAD = "eef6bf319f53e4434d5f99bf54bc7f78c1b41f75"
EXPECTED_COUNTED = 2620
MAX_HOLD_BARS = 576
STARTING_EQUITY = 10000.0
BAR_MINUTES = 5

_CAPTURED: list[dict[str, Any]] = []
_CAPTURE_STATE: dict[str, list[Any]] = {"fusions": [], "evaluations": []}
_CAPTURE_INSTALLED = False


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if hasattr(value, "value"):
        return value.value
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _observation_key(payload: Mapping[str, Any]) -> str:
    return "|".join((str(payload["symbol"]), str(payload["direction"]), str(payload["fold"]), str(payload["timestamp"]), str(payload["family"]), str(payload["fingerprint"])))


def _observation_from_payload(payload: Mapping[str, Any]) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=str(payload["symbol"]), direction=str(payload["direction"]), fold=int(payload["fold"]),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])), family=str(payload["family"]),
        decision=str(payload["decision"]), lifecycle=str(payload["lifecycle"]), fingerprint=str(payload["fingerprint"]),
        rearm_parent=payload.get("rearm_parent"), poi_id=str(payload["poi_id"]),
        liquidity_ids=tuple(payload.get("liquidity_ids", ())), interaction_ids=tuple(payload.get("interaction_ids", ())),
        anchor_id=payload.get("anchor_id"), structure_id=payload.get("structure_id"),
        evidence_ids=tuple(payload.get("evidence_ids", ())), evidence_cluster_ids=tuple(payload.get("evidence_cluster_ids", ())),
        economics_valid=bool(payload["economics_valid"]), risk_valid=bool(payload["risk_valid"]),
        block_reasons=tuple(payload.get("block_reasons", ())), hard_blocks=tuple(payload.get("hard_blocks", ())),
    )


def _install_capture_transport() -> None:
    global _CAPTURE_INSTALLED
    if _CAPTURE_INSTALLED:
        return
    original_fuse = runner.fuse_scenario
    original_evaluate = runner.evaluate_candidate
    original_build = runner._build_observation

    def capture_fuse(*args: Any, **kwargs: Any) -> Any:
        result = original_fuse(*args, **kwargs)
        _CAPTURE_STATE["fusions"].append(result)
        return result

    def capture_evaluate(candidate: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_evaluate(candidate, *args, **kwargs)
        _CAPTURE_STATE["evaluations"].append((candidate, result))
        return result

    def capture_build(*args: Any, **kwargs: Any) -> Any:
        _CAPTURE_STATE["fusions"].clear()
        _CAPTURE_STATE["evaluations"].clear()
        observation = original_build(*args, **kwargs)
        if observation is None:
            return None
        if not _CAPTURE_STATE["evaluations"] or not _CAPTURE_STATE["fusions"]:
            raise AssertionError("frozen geometry capture missed P5/P6 objects")
        candidate, admission = _CAPTURE_STATE["evaluations"][-1]
        final_fusion = _CAPTURE_STATE["fusions"][-1]
        observation_payload = partition._observation_to_dict(observation)
        record = {
            "observation": observation_payload,
            "observation_key": _observation_key(observation_payload),
            "reference_geometry": {
                "entry_price": float(candidate.entry_price), "stop_price": float(candidate.stop_price),
                "target_price": float(candidate.target_price), "leverage": float(candidate.leverage or 0.0),
                "margin_mode": str(candidate.margin_mode),
                "liquidation_price": float(candidate.liquidation_price) if candidate.liquidation_price is not None else None,
                "correlation_cluster": str(candidate.correlation_cluster), "dependency_ids": list(candidate.dependency_ids),
            },
            "p5": {"admission_decision": admission.decision.value, "economics": asdict(admission.economics),
                   "position": asdict(admission.position), "reasons": list(admission.reasons)},
            "p6": {"scenario_id": final_fusion.scenario.scenario_id, "decision": final_fusion.decision.value,
                   "score_0_100": float(final_fusion.scenario.total_score_0_100), "state": final_fusion.scenario.state.value},
        }
        if record["p6"]["decision"] != observation.decision:
            raise AssertionError("captured P6 decision differs from observation")
        _CAPTURED.append(record)
        return observation

    runner.fuse_scenario = capture_fuse
    runner.evaluate_candidate = capture_evaluate
    runner._build_observation = capture_build
    _CAPTURE_INSTALLED = True


def scan_geometry_shard(symbol: str, fold: int, shard_index: int, shard_count: int, output: Path) -> dict[str, Any]:
    _install_capture_transport()
    _CAPTURED.clear()
    observation_output = output.with_suffix(".recognition.json")
    payload = p7_shards.scan_shard(symbol, fold, shard_index, shard_count, observation_output)
    captured_keys = [_observation_key(row["observation"]) for row in _CAPTURED]
    observation_keys = [_observation_key(row) for row in payload["observations"]]
    if captured_keys != observation_keys:
        raise AssertionError("geometry capture is not one-to-one with frozen observations")
    result = {
        "p9_id": P9_ID, "candidate_id": CANDIDATE_ID, "recognition_id": payload["recognition_id"],
        "symbol": symbol, "fold": fold, "shard_index": shard_index, "shard_count": shard_count,
        "data_manifest_sha256": payload["data_manifest_sha256"], "source": payload["source"],
        "interval": payload["interval"], "start_inclusive": payload["start_inclusive"],
        "end_inclusive": payload["end_inclusive"], "diagnostics": payload["diagnostics"], "records": list(_CAPTURED),
    }
    _write_json(output, result)
    observation_output.unlink(missing_ok=True)
    return result


def merge_geometry_shards(paths: Iterable[Path], symbol: str, fold: int, output: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    if not payloads:
        raise ValueError("no P9 geometry shards")
    shard_counts = {int(payload["shard_count"]) for payload in payloads}
    if len(shard_counts) != 1:
        raise ValueError("P9 shard count mismatch")
    shard_count = next(iter(shard_counts))
    if len(payloads) != shard_count:
        raise ValueError(f"expected {shard_count} P9 shards, got {len(payloads)}")
    if {int(payload["shard_index"]) for payload in payloads} != set(range(shard_count)):
        raise ValueError("P9 shard index mismatch")
    if {payload["symbol"] for payload in payloads} != {symbol} or {int(payload["fold"]) for payload in payloads} != {fold}:
        raise ValueError("P9 shard partition mismatch")
    if {payload["p9_id"] for payload in payloads} != {P9_ID}:
        raise ValueError("P9 id mismatch")
    if len({payload["data_manifest_sha256"] for payload in payloads}) != 1:
        raise ValueError("P9 data manifest mismatch")
    ordered = sorted(payloads, key=lambda payload: int(payload["shard_index"]))
    spans = [(int(payload["diagnostics"]["shard_relative_start"]), int(payload["diagnostics"]["shard_relative_end"])) for payload in ordered]
    expected_start = 0
    for start, end in spans:
        if start != expected_start or end <= start:
            raise ValueError("P9 shard coverage is not contiguous")
        expected_start = end
    fold_boundaries = int(ordered[0]["diagnostics"]["fold_boundaries_total"])
    if expected_start != fold_boundaries:
        raise ValueError("P9 shard coverage incomplete")
    records = [record for payload in ordered for record in payload["records"]]
    keys = [_observation_key(record["observation"]) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate observation key inside P9 partition")
    result = {
        "p9_id": P9_ID, "candidate_id": CANDIDATE_ID, "recognition_id": ordered[0]["recognition_id"],
        "symbol": symbol, "fold": fold, "data_manifest_sha256": ordered[0]["data_manifest_sha256"],
        "source": ordered[0]["source"], "interval": ordered[0]["interval"],
        "start_inclusive": ordered[0]["start_inclusive"], "end_inclusive": ordered[0]["end_inclusive"],
        "execution_shards": shard_count, "records": records,
    }
    _write_json(output, result)
    return result


@dataclass(frozen=True)
class ResolvedOutcome:
    observation_key: str
    fingerprint: str
    symbol: str
    direction: str
    fold: int
    family: str
    decision: str
    signal_time: str
    executable_status: str
    raw_entry_price: float | None
    entry_fill_price: float | None
    stop_price: float
    target_price: float
    raw_exit_price: float | None
    exit_fill_price: float | None
    exit_time: str | None
    exit_reason: str | None
    bars_held: int
    minutes_held: int
    same_bar_ambiguity: bool
    gross_return_pct: float | None
    net_return_pct: float | None
    net_r: float | None
    mae_pct: float | None
    mfe_pct: float | None
    p5_net_rr: float
    p6_score_0_100: float
    reference_stop_move_pct: float
    reference_margin_pct_equity: float


def _round(value: float | None, digits: int = 10) -> float | None:
    return None if value is None else round(float(value), digits)


def resolve_outcome(record: Mapping[str, Any], candles: Sequence[Any], cost_model: CostModel | None = None) -> ResolvedOutcome:
    costs = cost_model or CostModel()
    obs = record["observation"]
    geometry = record["reference_geometry"]
    signal_time = datetime.fromisoformat(str(obs["timestamp"]))
    times = [candle.time for candle in candles]
    index = bisect.bisect_left(times, signal_time)
    direction = str(obs["direction"])
    stop = float(geometry["stop_price"])
    target = float(geometry["target_price"])
    economics = record["p5"]["economics"]
    position = record["p5"]["position"]
    base = dict(
        observation_key=str(record["observation_key"]), fingerprint=str(obs["fingerprint"]), symbol=str(obs["symbol"]),
        direction=direction, fold=int(obs["fold"]), family=str(obs["family"]), decision=str(obs["decision"]),
        signal_time=signal_time.isoformat(), stop_price=stop, target_price=target,
        p5_net_rr=float(economics["net_rr"]), p6_score_0_100=float(record["p6"]["score_0_100"]),
        reference_stop_move_pct=float(economics["stop_move_pct"]),
        reference_margin_pct_equity=float(position["margin_pct_equity"]),
    )
    if index >= len(candles):
        return ResolvedOutcome(**base, executable_status="NO_FUTURE_BAR", raw_entry_price=None, entry_fill_price=None,
                               raw_exit_price=None, exit_fill_price=None, exit_time=None, exit_reason=None, bars_held=0,
                               minutes_held=0, same_bar_ambiguity=False, gross_return_pct=None, net_return_pct=None,
                               net_r=None, mae_pct=None, mfe_pct=None)
    raw_entry = float(candles[index].open)
    entry_slippage = costs.entry_slippage_pct / 100.0
    entry_fill = raw_entry * (1.0 + entry_slippage if direction == "LONG" else 1.0 - entry_slippage)
    valid = stop < entry_fill < target if direction == "LONG" else target < entry_fill < stop
    if not valid:
        return ResolvedOutcome(**base, executable_status="NON_EXECUTABLE_GAP", raw_entry_price=_round(raw_entry),
                               entry_fill_price=_round(entry_fill), raw_exit_price=None, exit_fill_price=None,
                               exit_time=None, exit_reason=None, bars_held=0, minutes_held=0, same_bar_ambiguity=False,
                               gross_return_pct=None, net_return_pct=None, net_r=None, mae_pct=None, mfe_pct=None)
    horizon = candles[index:min(len(candles), index + MAX_HOLD_BARS)]
    same_bar = False
    raw_exit: float | None = None
    exit_reason: str | None = None
    exit_bar: Any | None = None
    min_low = entry_fill
    max_high = entry_fill
    for bar in horizon:
        min_low = min(min_low, float(bar.low))
        max_high = max(max_high, float(bar.high))
        if direction == "LONG":
            stop_hit, target_hit = float(bar.low) <= stop, float(bar.high) >= target
        else:
            stop_hit, target_hit = float(bar.high) >= stop, float(bar.low) <= target
        if stop_hit and target_hit:
            same_bar, raw_exit, exit_reason, exit_bar = True, stop, "STOP_FIRST", bar
            break
        if stop_hit:
            raw_exit, exit_reason, exit_bar = stop, "STOP", bar
            break
        if target_hit:
            raw_exit, exit_reason, exit_bar = target, "TARGET", bar
            break
    if exit_bar is None:
        exit_bar = horizon[-1]
        raw_exit = float(exit_bar.close)
        exit_reason = "TIME_EXIT" if len(horizon) == MAX_HOLD_BARS else "END_OF_DATA"
    bars_held = horizon.index(exit_bar) + 1
    exit_time = exit_bar.time + timedelta(minutes=BAR_MINUTES)
    exit_slippage = costs.exit_slippage_pct / 100.0
    exit_fill = float(raw_exit) * (1.0 - exit_slippage if direction == "LONG" else 1.0 + exit_slippage)
    quantity = 1.0 / entry_fill
    gross_fraction = quantity * (exit_fill - entry_fill) if direction == "LONG" else quantity * (entry_fill - exit_fill)
    entry_fee = costs.entry_fee_pct / 100.0
    exit_fee = quantity * exit_fill * costs.exit_fee_pct / 100.0
    net_fraction = gross_fraction - entry_fee - exit_fee - costs.expected_funding_pct / 100.0 - costs.cost_buffer_pct / 100.0
    effective_risk = max(1e-12, float(economics["effective_net_loss_pct"]) / 100.0)
    net_r = net_fraction / effective_risk
    if direction == "LONG":
        mae, mfe = max(0.0, (entry_fill - min_low) / entry_fill * 100.0), max(0.0, (max_high - entry_fill) / entry_fill * 100.0)
    else:
        mae, mfe = max(0.0, (max_high - entry_fill) / entry_fill * 100.0), max(0.0, (entry_fill - min_low) / entry_fill * 100.0)
    return ResolvedOutcome(
        **base, executable_status="EXECUTABLE", raw_entry_price=_round(raw_entry), entry_fill_price=_round(entry_fill),
        raw_exit_price=_round(raw_exit), exit_fill_price=_round(exit_fill), exit_time=exit_time.isoformat(),
        exit_reason=exit_reason, bars_held=bars_held, minutes_held=bars_held * BAR_MINUTES,
        same_bar_ambiguity=same_bar, gross_return_pct=_round(gross_fraction * 100.0),
        net_return_pct=_round(net_fraction * 100.0), net_r=_round(net_r), mae_pct=_round(mae), mfe_pct=_round(mfe),
    )


def _capacity_plan(outcome: ResolvedOutcome, equity: float, active: Sequence[Mapping[str, Any]], limits: RiskLimits) -> dict[str, float]:
    stop_fraction = max(1e-12, outcome.reference_stop_move_pct / 100.0)
    risk_amount = equity * limits.risk_per_position_pct / 100.0
    notional = risk_amount / stop_fraction
    leverage = 20.0
    margin = notional / leverage
    open_risk = sum(float(position["risk_amount"]) for position in active)
    used_margin = sum(float(position["margin"]) for position in active)
    open_notional = sum(float(position["notional"]) for position in active)
    return {
        "risk_amount": risk_amount, "notional": notional, "leverage": leverage, "margin": margin,
        "position_margin_pct": margin / equity * 100.0,
        "projected_open_risk_pct": (open_risk + risk_amount) / equity * 100.0,
        "projected_total_margin_pct": (used_margin + margin) / equity * 100.0,
        "projected_total_notional_multiple": (open_notional + notional) / equity,
    }


def simulate_portfolio(outcomes: Sequence[ResolvedOutcome], limits: RiskLimits | None = None) -> dict[str, Any]:
    limits = limits or RiskLimits()
    eligible = [outcome for outcome in outcomes if outcome.executable_status == "EXECUTABLE"]
    grouped: dict[str, list[ResolvedOutcome]] = {}
    for outcome in eligible:
        grouped.setdefault(outcome.signal_time, []).append(outcome)
    equity = STARTING_EQUITY
    active: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = [{"time": "START", "equity": STARTING_EQUITY}]

    def realize_until(timestamp: datetime | None) -> None:
        nonlocal equity
        closable = [position for position in active if timestamp is None or datetime.fromisoformat(str(position["outcome"]["exit_time"])) <= timestamp]
        closable.sort(key=lambda position: (position["outcome"]["exit_time"], position["outcome"]["fingerprint"]))
        for position in closable:
            outcome = position["outcome"]
            pnl = float(position["notional"]) * float(outcome["net_return_pct"]) / 100.0
            equity += pnl
            executed.append({**outcome, "admission_equity": _round(position["admission_equity"]),
                             "risk_amount": _round(position["risk_amount"]), "notional": _round(position["notional"]),
                             "margin": _round(position["margin"]), "pnl": _round(pnl), "equity_after_exit": _round(equity)})
            equity_curve.append({"time": outcome["exit_time"], "equity": _round(equity), "fingerprint": outcome["fingerprint"]})
            active.remove(position)

    for timestamp_text in sorted(grouped):
        timestamp = datetime.fromisoformat(timestamp_text)
        realize_until(timestamp)
        ranked: list[tuple[tuple[Any, ...], ResolvedOutcome]] = []
        for outcome in grouped[timestamp_text]:
            plan = _capacity_plan(outcome, equity, active, limits)
            ranked.append(((0 if outcome.decision == "HIGH_CONFIDENCE_SETUP" else 1, -outcome.p5_net_rr,
                            -outcome.p6_score_0_100, plan["position_margin_pct"], outcome.fingerprint), outcome))
        for _, outcome in sorted(ranked, key=lambda item: item[0]):
            plan = _capacity_plan(outcome, equity, active, limits)
            reasons: list[str] = []
            if plan["leverage"] > limits.max_leverage: reasons.append("leverage_above_max")
            if plan["position_margin_pct"] > limits.max_margin_per_position_pct: reasons.append("margin_per_position_above_max")
            if plan["projected_open_risk_pct"] > limits.max_total_open_risk_pct: reasons.append("total_open_risk_above_max")
            if plan["projected_total_margin_pct"] > limits.max_total_margin_pct: reasons.append("total_margin_above_max")
            if plan["projected_total_notional_multiple"] > limits.max_total_notional_multiple: reasons.append("total_notional_above_max")
            if equity <= 0: reasons.append("non_positive_equity")
            if reasons:
                rejected.append({"fingerprint": outcome.fingerprint, "signal_time": outcome.signal_time,
                                 "symbol": outcome.symbol, "direction": outcome.direction,
                                 "reason": "REJECT_PORTFOLIO_CAPACITY", "details": reasons})
                continue
            active.append({"outcome": asdict(outcome), "admission_equity": equity, "risk_amount": plan["risk_amount"],
                           "notional": plan["notional"], "margin": plan["margin"]})
    realize_until(None)
    if active:
        raise AssertionError("portfolio simulation ended with active positions")
    return {"starting_equity": STARTING_EQUITY, "ending_equity": _round(equity), "eligible_count": len(eligible),
            "executed_count": len(executed), "capacity_rejected_count": len(rejected), "executed": executed,
            "rejected": rejected, "equity_curve": equity_curve}


def _safe_mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _max_drawdown_pct(equity_curve: Sequence[Mapping[str, Any]]) -> float:
    peak = float(equity_curve[0]["equity"])
    maximum = 0.0
    for row in equity_curve:
        value = float(row["equity"])
        peak = max(peak, value)
        maximum = max(maximum, (peak - value) / peak * 100.0 if peak > 0 else 0.0)
    return maximum


def _group_metrics(rows: Sequence[Mapping[str, Any]], field: str, values: Sequence[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        sample = [row for row in rows if row[field] == value]
        net_rs, pnls = [float(row["net_r"]) for row in sample], [float(row["pnl"]) for row in sample]
        result[str(value)] = {"count": len(sample), "expectancy_r": _round(_safe_mean(net_rs)), "net_pnl": _round(sum(pnls)),
                              "win_rate_pct": _round(sum(pnl > 0 for pnl in pnls) / len(pnls) * 100.0 if pnls else 0.0)}
    return result


def summarize_portfolio(portfolio: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(portfolio["executed"])
    pnls, net_rs = [float(row["pnl"]) for row in rows], [float(row["net_r"]) for row in rows]
    net_returns = [float(row["net_return_pct"]) for row in rows]
    gross_profit, gross_loss = sum(v for v in pnls if v > 0), abs(sum(v for v in pnls if v < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (None if gross_profit == 0 else 999999.0)
    by_symbol = _group_metrics(rows, "symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT"])
    by_direction = _group_metrics(rows, "direction", ["LONG", "SHORT"])
    by_family = _group_metrics(rows, "family", ["LIQUIDITY_RAID_REVERSAL", "TREND_PULLBACK_CONTINUATION", "RANGE_BOUNDARY_ROTATION"])
    by_fold = _group_metrics(rows, "fold", list(range(10)))
    positive_by_symbol = {symbol: 0.0 for symbol in by_symbol}
    reasons: dict[str, int] = {}
    for row in rows:
        if float(row["pnl"]) > 0: positive_by_symbol[row["symbol"]] += float(row["pnl"])
        reasons[str(row["exit_reason"])] = reasons.get(str(row["exit_reason"]), 0) + 1
    concentration = max(positive_by_symbol.values()) / gross_profit * 100.0 if gross_profit > 0 else 100.0
    return {
        "executed_count": len(rows), "ending_equity": portfolio["ending_equity"],
        "total_net_return_pct": _round((float(portfolio["ending_equity"]) / STARTING_EQUITY - 1.0) * 100.0),
        "expectancy_net_pct": _round(_safe_mean(net_returns)), "expectancy_r": _round(_safe_mean(net_rs)),
        "median_net_r": _round(median(net_rs) if net_rs else 0.0), "profit_factor": _round(profit_factor),
        "win_rate_pct": _round(sum(v > 0 for v in pnls) / len(pnls) * 100.0 if pnls else 0.0),
        "max_drawdown_pct": _round(_max_drawdown_pct(portfolio["equity_curve"])),
        "gross_profit": _round(gross_profit), "gross_loss": _round(gross_loss),
        "average_mae_pct": _round(_safe_mean([float(row["mae_pct"]) for row in rows])),
        "average_mfe_pct": _round(_safe_mean([float(row["mfe_pct"]) for row in rows])),
        "average_minutes_held": _round(_safe_mean([float(row["minutes_held"]) for row in rows])),
        "same_bar_ambiguity_count": sum(bool(row["same_bar_ambiguity"]) for row in rows),
        "exit_reason_counts": dict(sorted(reasons.items())), "by_symbol": by_symbol, "by_direction": by_direction,
        "by_family": by_family, "by_fold": by_fold,
        "positive_expectancy_symbol_count": sum(float(v["expectancy_r"]) > 0 for v in by_symbol.values()),
        "positive_expectancy_fold_count": sum(float(v["expectancy_r"]) > 0 for v in by_fold.values()),
        "long_executed_count": int(by_direction["LONG"]["count"]), "short_executed_count": int(by_direction["SHORT"]["count"]),
        "max_positive_gross_profit_concentration_pct": _round(concentration),
    }


def evaluate_development(partition_paths: Iterable[Path], data_root: Path, p7_report_path: Path, p8_report_path: Path,
                         p8_manifest_path: Path, prereg_path: Path, output: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(partition_paths)]
    if len(payloads) != 50:
        raise ValueError(f"expected 50 P9 geometry partitions, got {len(payloads)}")
    expected_keys = {(symbol, fold) for symbol in runner.ALLOWED_SYMBOLS for fold in range(10)}
    if {(payload["symbol"], int(payload["fold"])) for payload in payloads} != expected_keys:
        raise ValueError("P9 partition universe/fold mismatch")
    if len({payload["data_manifest_sha256"] for payload in payloads}) != 1:
        raise ValueError("P9 partition manifest mismatch")
    records = [record for payload in payloads for record in payload["records"]]
    observations = [_observation_from_payload(record["observation"]) for record in records]
    deduped, duplicate_count = dedupe_global(observations)
    counted = tuple(row for row in deduped if is_counted(row))
    record_map = {record["observation_key"]: record for record in records}
    selected_keys = [_observation_key(partition._observation_to_dict(row)) for row in counted]
    if len(selected_keys) != len(set(selected_keys)):
        raise AssertionError("selected P9 record keys are not unique")
    missing_geometry = [key for key in selected_keys if key not in record_map]
    selected_records = [record_map[key] for key in selected_keys if key in record_map]
    p7_report = json.loads(p7_report_path.read_text(encoding="utf-8"))
    p8_report = json.loads(p8_report_path.read_text(encoding="utf-8"))
    p8_manifest = json.loads(p8_manifest_path.read_text(encoding="utf-8"))
    authoritative_fingerprints = set(p7_report["recognition"]["fingerprints"])
    selected_fingerprints = {row.fingerprint for row in counted}
    parity = {
        "counted": len(counted), "expected_counted": EXPECTED_COUNTED, "duplicate_rows": duplicate_count,
        "missing_geometry_count": len(missing_geometry),
        "missing_fingerprint_count": len(authoritative_fingerprints - selected_fingerprints),
        "extra_fingerprint_count": len(selected_fingerprints - authoritative_fingerprints),
        "exact_fingerprint_set": selected_fingerprints == authoritative_fingerprints,
        "valid": len(counted) == EXPECTED_COUNTED and not missing_geometry and selected_fingerprints == authoritative_fingerprints,
    }
    if p8_report.get("status") != "PASS" or int(p8_report["equivalence"]["mismatch_count"]) != 0:
        raise ValueError("authoritative P8 freeze is not PASS with zero mismatches")
    if p8_manifest.get("missing_files") != [] or p8_manifest.get("hashed_file_count") != p8_manifest.get("required_file_count"):
        raise ValueError("authoritative P8 freeze manifest incomplete")
    _, candles_by_symbol = runner.load_locked_dataset(data_root)
    outcomes = [resolve_outcome(record, candles_by_symbol[record["observation"]["symbol"]]) for record in selected_records]
    executable_counts: dict[str, int] = {}
    for outcome in outcomes:
        executable_counts[outcome.executable_status] = executable_counts.get(outcome.executable_status, 0) + 1
    portfolio = simulate_portfolio(outcomes)
    metrics = summarize_portfolio(portfolio)
    gate_checks = {
        "recognition_parity": bool(parity["valid"]), "executed_at_least_200": metrics["executed_count"] >= 200,
        "ending_equity_above_start": float(metrics["ending_equity"]) > STARTING_EQUITY,
        "positive_expectancy_r": float(metrics["expectancy_r"]) > 0.0,
        "profit_factor_at_least_1_10": metrics["profit_factor"] is not None and float(metrics["profit_factor"]) >= 1.10,
        "max_drawdown_at_most_15pct": float(metrics["max_drawdown_pct"]) <= 15.0,
        "positive_symbols_at_least_3": int(metrics["positive_expectancy_symbol_count"]) >= 3,
        "positive_folds_at_least_6": int(metrics["positive_expectancy_fold_count"]) >= 6,
        "long_at_least_50": int(metrics["long_executed_count"]) >= 50,
        "short_at_least_50": int(metrics["short_executed_count"]) >= 50,
        "symbol_profit_concentration_at_most_60pct": float(metrics["max_positive_gross_profit_concentration_pct"]) <= 60.0,
        "deterministic_geometry_mapping": len(selected_records) == len(selected_keys) and len(selected_keys) == len(set(selected_keys)),
    }
    geometry_stream = [{"observation_key": record["observation_key"], "observation": record["observation"],
                        "reference_geometry": record["reference_geometry"], "p5": record["p5"], "p6": record["p6"]}
                       for record in sorted(selected_records, key=lambda item: item["observation_key"])]
    outcome_stream = [asdict(outcome) for outcome in sorted(outcomes, key=lambda item: item.observation_key)]
    source_files = [Path(__file__), Path("strategy_lab/p9_development_profitability_v1_smoke_test.py"), prereg_path]
    hashes = {
        "preregistration_sha256": _sha256_path(prereg_path), "p7_report_sha256": _sha256_path(p7_report_path),
        "p8_report_sha256": _sha256_path(p8_report_path), "p8_manifest_sha256": _sha256_path(p8_manifest_path),
        "locked_data_manifest_sha256": _sha256_path(data_root / "p7_full_recognition_data_manifest_v1.json"),
        "geometry_stream_sha256": _sha256_bytes(_canonical_bytes(geometry_stream)),
        "outcome_stream_sha256": _sha256_bytes(_canonical_bytes(outcome_stream)),
        "source_files": {str(path): _sha256_path(path) for path in source_files},
    }
    report = {
        "p9_id": P9_ID, "candidate_id": CANDIDATE_ID, "status": "PASS" if all(gate_checks.values()) else "FAIL",
        "development_only": True, "holdout": False,
        "authoritative": {"p7_run_id": P7_RUN_ID, "p7_head": P7_HEAD, "p8_run_id": P8_RUN_ID, "p8_head": P8_HEAD},
        "contract": {"symbols": list(runner.ALLOWED_SYMBOLS), "directions": ["LONG", "SHORT"], "fold_count": 10,
                     "max_hold_5m_bars": MAX_HOLD_BARS, "same_bar_rule": "STOP_FIRST",
                     "entry_rule": "FIRST_5M_OPEN_AT_OR_AFTER_RECOGNITION_TIMESTAMP_WITH_ADVERSE_SLIPPAGE",
                     "initial_equity": STARTING_EQUITY, "cost_model": asdict(CostModel()), "risk_limits": asdict(RiskLimits())},
        "recognition_parity": parity, "executable_status_counts": dict(sorted(executable_counts.items())),
        "portfolio": {"eligible_count": portfolio["eligible_count"], "executed_count": portfolio["executed_count"],
                      "capacity_rejected_count": portfolio["capacity_rejected_count"], "metrics": metrics},
        "gate_checks": gate_checks, "hashes": hashes,
    }
    report["report_digest_sha256"] = _sha256_bytes(_canonical_bytes(report))
    _write_json(output, report)
    _write_json(output.with_name("p9_development_outcomes_v1.json"), outcome_stream)
    _write_json(output.with_name("p9_development_portfolio_trades_v1.json"),
                {"executed": portfolio["executed"], "rejected": portfolio["rejected"], "equity_curve": portfolio["equity_curve"]})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--symbol", required=True); scan.add_argument("--fold", required=True, type=int)
    scan.add_argument("--shard-index", required=True, type=int); scan.add_argument("--shard-count", required=True, type=int)
    scan.add_argument("--output", required=True, type=Path)
    merge = sub.add_parser("merge")
    merge.add_argument("--input-dir", required=True, type=Path); merge.add_argument("--symbol", required=True)
    merge.add_argument("--fold", required=True, type=int); merge.add_argument("--output", required=True, type=Path)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--input-dir", required=True, type=Path); evaluate.add_argument("--data-root", required=True, type=Path)
    evaluate.add_argument("--p7-report", required=True, type=Path); evaluate.add_argument("--p8-report", required=True, type=Path)
    evaluate.add_argument("--p8-manifest", required=True, type=Path); evaluate.add_argument("--prereg", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "scan":
        scan_geometry_shard(args.symbol.upper(), args.fold, args.shard_index, args.shard_count, args.output); return 0
    if args.command == "merge":
        merge_geometry_shards(args.input_dir.rglob(f"p9_geometry_shard_{args.symbol.upper()}_{args.fold}_*.json"),
                              args.symbol.upper(), args.fold, args.output); return 0
    report = evaluate_development(args.input_dir.rglob("p9_geometry_partition_*.json"), args.data_root, args.p7_report,
                                  args.p8_report, args.p8_manifest, args.prereg, args.output)
    print(json.dumps({"p9_id": report["p9_id"], "status": report["status"],
                      "executed": report["portfolio"]["executed_count"],
                      "expectancy_r": report["portfolio"]["metrics"]["expectancy_r"],
                      "profit_factor": report["portfolio"]["metrics"]["profit_factor"],
                      "max_drawdown_pct": report["portfolio"]["metrics"]["max_drawdown_pct"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
