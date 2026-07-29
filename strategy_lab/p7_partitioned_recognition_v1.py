#!/usr/bin/env python3
"""Technical partition runner for exact P7 full recognition.

Execution is split into the preregistered 5 symbols x 10 chronological folds.
Each fold job reconstructs the same causal history available at every evaluated
closed candle, emits only observations belonging to its fixed fold, and the
aggregate step performs the original global fingerprint de-duplication and gate.
No frozen recognition semantics are changed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_SYMBOLS,
    RecognitionObservation,
    dedupe_global,
    is_counted,
    report_to_no_outcome_dict,
    run_full_recognition,
)
import strategy_lab.p7_full_recognition_runner_v1 as runner

RECOGNITION_ID = runner.RECOGNITION_ID
DATA_ROOT = runner.DATA_ROOT
REPORT_PATH = runner.REPORT_PATH
ScenarioFamily = runner.ScenarioFamily
FOLD_COUNT = runner.FOLD_COUNT


def _observation_to_dict(row: RecognitionObservation) -> dict[str, Any]:
    payload = asdict(row)
    payload["timestamp"] = row.timestamp.isoformat()
    return payload


def _observation_from_dict(payload: dict[str, Any]) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=str(payload["symbol"]),
        direction=str(payload["direction"]),
        fold=int(payload["fold"]),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])),
        family=str(payload["family"]),
        decision=str(payload["decision"]),
        lifecycle=str(payload["lifecycle"]),
        fingerprint=str(payload["fingerprint"]),
        rearm_parent=payload.get("rearm_parent"),
        poi_id=str(payload["poi_id"]),
        liquidity_ids=tuple(payload.get("liquidity_ids", ())),
        interaction_ids=tuple(payload.get("interaction_ids", ())),
        anchor_id=payload.get("anchor_id"),
        structure_id=payload.get("structure_id"),
        evidence_ids=tuple(payload.get("evidence_ids", ())),
        evidence_cluster_ids=tuple(payload.get("evidence_cluster_ids", ())),
        economics_valid=bool(payload["economics_valid"]),
        risk_valid=bool(payload["risk_valid"]),
        block_reasons=tuple(payload.get("block_reasons", ())),
        hard_blocks=tuple(payload.get("hard_blocks", ())),
    )


def _fold_bounds(boundaries: Sequence[datetime], fold: int) -> tuple[int, int]:
    if fold not in range(FOLD_COUNT):
        raise ValueError(f"fold must be in [0, {FOLD_COUNT - 1}]")
    base, remainder = divmod(len(boundaries), FOLD_COUNT)
    start = fold * base + min(fold, remainder)
    size = base + (1 if fold < remainder else 0)
    return start, start + size


def scan_symbol_fold(symbol: str, candles: Sequence[Any], fold: int) -> tuple[list[RecognitionObservation], dict[str, Any]]:
    """Run the frozen scan for one exact chronological fold with full prior history."""
    engine = runner.MtfDealingRangeEngine(candles)
    bars_5m_all = [bar for bar in engine.bars["5m"] if bar.symbol == symbol]
    bars_15m_all = [bar for bar in engine.bars["15m"] if bar.symbol == symbol]
    boundaries = [bar.close_time for bar in bars_15m_all]
    folds = runner.assign_folds(boundaries)
    start, end = _fold_bounds(boundaries, fold)
    selected = bars_15m_all[start:end]
    if not selected or any(folds[bar.close_time] != fold for bar in selected):
        raise AssertionError("fold partition mismatch")

    context_cfg = runner.ContextLiquidityConfig()
    interaction_cfg = runner.InteractionConfig()
    interaction_engine = runner.InteractionEngineV1(interaction_cfg)
    poi_engine = runner.POIImbalanceEngine()
    levels_all = runner._precompute_levels(engine, symbol, boundaries, context_cfg)
    context_cache: dict[datetime, Any] = {}
    poi_cache: dict[datetime, Any] = {}
    observations: list[RecognitionObservation] = []
    diagnostics = {
        "symbol": symbol,
        "fold": fold,
        "boundaries": len(boundaries),
        "fold_boundaries": len(selected),
        "anchors_seen": 0,
        "family_specs": 0,
        "entry_geometries": 0,
        "observations": 0,
        "raw_levels": len(levels_all),
    }

    first_open = selected[0].open_time
    bars_15m = [bar for bar in bars_15m_all if bar.open_time < first_open]
    first_close = selected[0].close_time
    cursor_5m = 0
    while cursor_5m < len(bars_5m_all) and bars_5m_all[cursor_5m].close_time < first_close:
        cursor_5m += 1
    bars_5m = list(bars_5m_all[:cursor_5m])

    for current_15m in selected:
        timestamp = current_15m.close_time
        while cursor_5m < len(bars_5m_all) and bars_5m_all[cursor_5m].close_time <= timestamp:
            bars_5m.append(bars_5m_all[cursor_5m])
            cursor_5m += 1
        bars_15m.append(current_15m)
        cache_key = timestamp.replace(minute=0, second=0, microsecond=0)
        if cache_key not in context_cache:
            context_cache[cache_key] = runner._context_view(engine, symbol, timestamp, context_cfg)
        view = context_cache[cache_key]
        if cache_key not in poi_cache:
            poi_cache[cache_key] = runner._active_pois(engine, timestamp, poi_engine)
        pois, evidence_map = poi_cache[cache_key]
        if view.hard_block or not pois:
            continue
        lookback = interaction_cfg.atr_length + max(
            interaction_cfg.inducement_max_age_bars,
            interaction_cfg.anchor_expiry_bars,
            interaction_cfg.acceptance_closes,
            interaction_cfg.invalidation_closes,
        ) + 2
        recent_15m = bars_15m[-lookback:]
        relevant_levels = runner._relevant_levels(levels_all, bars_5m, recent_15m, timestamp, context_cfg)
        relevant_pois = tuple(
            poi for poi in pois
            if any(bar.high >= poi.low and bar.low <= poi.high for bar in recent_15m)
        )
        if not relevant_levels and not relevant_pois:
            continue
        interaction = interaction_engine.snapshot(
            symbol=symbol,
            timeframe="15m",
            bars=recent_15m,
            pois=relevant_pois,
            levels=relevant_levels,
            evaluated_at=timestamp,
        )
        diagnostics["anchors_seen"] += len(interaction.anchors)
        specs = runner._family_specs(
            interaction,
            {poi.poi_id: poi for poi in relevant_pois},
            {level.level_id: level for level in relevant_levels},
            view,
            recent_15m,
        )
        diagnostics["family_specs"] += len(specs)
        for spec in specs:
            structure = runner.evaluate_execution_structure(
                spec.anchor,
                {
                    "5m": [bar for bar in bars_5m if bar.close_time >= spec.anchor.confirmed_at],
                    "15m": [bar for bar in bars_15m if bar.close_time >= spec.anchor.confirmed_at],
                },
                timestamp,
            )
            if not runner.apply_family_policy(structure, spec.policy_family).allowed:
                continue
            geometry = runner._entry_geometry(structure, spec.family, bars_15m, timestamp)
            if geometry is None:
                continue
            entry_price, entry_timestamp = geometry
            diagnostics["entry_geometries"] += 1
            target, target_level = runner._select_target(
                levels_all,
                bars_5m,
                spec.anchor.confirmed_at,
                entry_price,
                spec.anchor.direction,
                context_cfg,
            )
            if target is None or target_level is None:
                continue
            observation = runner._build_observation(
                symbol,
                fold,
                entry_timestamp,
                spec,
                view,
                structure,
                entry_price,
                target,
                target_level,
                bars_15m,
                evidence_map,
            )
            if observation is not None:
                observations.append(observation)
    diagnostics["observations"] = len(observations)
    return observations, diagnostics


def scan_partition(symbol: str, fold: int, output: Path, root: Path = DATA_ROOT) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in ALLOWED_SYMBOLS:
        raise ValueError(f"unexpected symbol: {symbol}")
    manifest, candles_by_symbol = runner.load_locked_dataset(root)
    rows, diagnostics = scan_symbol_fold(symbol, candles_by_symbol[symbol], fold)
    payload = {
        "recognition_id": RECOGNITION_ID,
        "symbol": symbol,
        "fold": fold,
        "data_manifest_sha256": hashlib.sha256((root / "p7_full_recognition_data_manifest_v1.json").read_bytes()).hexdigest(),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"],
        "end_inclusive": manifest["end_inclusive"],
        "diagnostics": diagnostics,
        "observations": [_observation_to_dict(row) for row in rows],
    }
    runner._assert_no_outcomes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runner._jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return payload


def aggregate_partitions(paths: Iterable[Path], output: Path = REPORT_PATH) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    expected = len(ALLOWED_SYMBOLS) * FOLD_COUNT
    if len(payloads) != expected:
        raise ValueError(f"expected {expected} symbol-fold partitions, got {len(payloads)}")
    actual_keys = {(payload["symbol"], int(payload["fold"])) for payload in payloads}
    expected_keys = {(symbol, fold) for symbol in ALLOWED_SYMBOLS for fold in range(FOLD_COUNT)}
    if actual_keys != expected_keys:
        raise ValueError("partition universe/fold mismatch")
    if {payload["recognition_id"] for payload in payloads} != {RECOGNITION_ID}:
        raise ValueError("recognition id mismatch")
    manifest_shas = {payload["data_manifest_sha256"] for payload in payloads}
    if len(manifest_shas) != 1:
        raise ValueError("partition manifest mismatch")

    all_rows = [
        _observation_from_dict(row)
        for payload in payloads
        for row in payload["observations"]
    ]
    for payload in payloads:
        if any(int(row["fold"]) != int(payload["fold"]) for row in payload["observations"]):
            raise ValueError("observation escaped its fixed fold")
    report = run_full_recognition(all_rows)
    deduped, _ = dedupe_global(all_rows)
    counted_rows = tuple(row for row in deduped if is_counted(row))
    result = {
        "recognition_id": RECOGNITION_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_1",
        "data_manifest_sha256": next(iter(manifest_shas)),
        "source": payloads[0]["source"],
        "interval": payloads[0]["interval"],
        "start_inclusive": payloads[0]["start_inclusive"],
        "end_inclusive": payloads[0]["end_inclusive"],
        "fold_count": FOLD_COUNT,
        "status": "PASS" if report.gate_pass else "FAIL",
        "recognition": report_to_no_outcome_dict(report),
        "by_family": {
            family.value: sum(row.family == family.value for row in counted_rows)
            for family in ScenarioFamily
        },
        "diagnostics": [payload["diagnostics"] for payload in payloads],
        "execution_topology": "FIFTY_SYMBOL_FOLD_PARTITIONS_THEN_GLOBAL_DEDUPE_V1",
    }
    runner._assert_no_outcomes(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runner._jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--symbol", required=True)
    scan.add_argument("--fold", required=True, type=int)
    scan.add_argument("--output", required=True, type=Path)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--input-dir", required=True, type=Path)
    aggregate.add_argument("--output", default=REPORT_PATH, type=Path)
    args = parser.parse_args()

    if args.command == "scan":
        scan_partition(args.symbol, args.fold, args.output)
        return 0
    paths = tuple(args.input_dir.rglob("p7_partition_*.json"))
    result = aggregate_partitions(paths, args.output)
    print(json.dumps({
        "recognition_id": result["recognition_id"],
        "status": result["status"],
        "independent_entry_ready": result["recognition"]["independent_entry_ready"],
        "gate_pass": result["recognition"]["gate_pass"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
