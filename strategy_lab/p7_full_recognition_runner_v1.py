#!/usr/bin/env python3
"""SMOKE CORE 1.0 P7 full outcome-blind recognition runner.

The runner is a deterministic adapter over the frozen P1-P6 engines.  It reads
only the locked Binance Vision OHLCV artifact, evaluates fully closed candles,
and emits P7 RecognitionObservation rows.  It never reads or serializes market
outcomes.

Adapter mapping is contract-derived:
- P1 POIs are evaluated on closed 1h and 4h bars.
- P2 context uses the frozen 1M/1w/1d/4h/1h aggregation and P2 liquidity
  constructors.  Historical pivot/equal/period/session/range levels are
  generated only after their native confirmed_at timestamps.
- P3 exact POI/liquidity interactions provide anchors.  Raid reversal requires
  an exact P3 INDUCEMENT_TO_REACTION relation.  Trend continuation requires an
  exact POI rejection anchor aligned with frozen HTF trend/regime.  Range
  rotation requires an exact POI rejection overlapping a confirmed P2
  RANGE_HIGH/RANGE_LOW and a close back inside that range.
- P4 local structure and frozen family policy decide confirmation.  Raid and
  range families use the next aligned 15m open; continuation uses the first
  causal retest of the predefined P4 boundary, within the P0 entry window.
- P5 uses the exact preselected P2 target and P4 protected swing; neither is
  moved to manufacture RR.
- P6 receives deterministic evidence records whose ids point to exact upstream
  objects.  Derived evidence retains its original cluster lineage.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from strategy_lab.context_liquidity_engine_v1 import (
    ContextLiquidityConfig,
    ContextRegime,
    LiquidityKind,
    LiquidityLevelV1,
    LiquiditySide,
    TimeframeContextState,
    _aggregate_context,
    _deduplicate_levels,
    _equal_liquidity_levels,
    _period_liquidity_levels,
    _pivot_liquidity_levels,
    _range_liquidity_levels,
    _session_liquidity_levels,
    build_timeframe_state,
    evaluate_liquidity_state,
    target_candidates,
)
from strategy_lab.economics_risk_portfolio_v1 import (
    AccountState,
    AdmissionDecision,
    CostModel,
    ExecutionCandidate,
    Side as RiskSide,
    evaluate_candidate,
)
from strategy_lab.execution_family_policy_v1 import (
    ScenarioFamily as PolicyFamily,
    apply_family_policy,
)
from strategy_lab.execution_structure_v1 import (
    ExecutionState,
    LocalStructureV1,
    evaluate_execution_structure,
)
from strategy_lab.interaction_engine_v1 import (
    AnchorEventV1,
    AnchorKind,
    InteractionConfig,
    InteractionEngineV1,
    InteractionEventV1,
    InteractionKind,
    InteractionRelationV1,
    InteractionState,
    RelationKind,
)
from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, MtfDealingRangeEngine
from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_SYMBOLS,
    RecognitionObservation,
    dedupe_global,
    is_counted,
    report_to_no_outcome_dict,
    run_full_recognition,
)
from strategy_lab.poi_imbalance_engine_v1 import (
    Direction,
    EvidenceRecord as P1EvidenceRecord,
    EvidenceRelation as P1EvidenceRelation,
    POIImbalanceEngine,
    POIState,
    POIZone,
)
from strategy_lab.scenario_fusion_v1 import (
    EvidenceInput,
    EvidenceRelation,
    FusionInput,
    ScenarioFamily,
    ScenarioState,
    fuse_scenario,
)

RECOGNITION_ID = "SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1"
DATA_ROOT = Path("research_outputs/p7_full_recognition_data_v1")
REPORT_PATH = Path("research_outputs/p7_full_recognition_report_v1.json")
START = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
END_OPEN = datetime(2024, 6, 30, 23, 55, tzinfo=timezone.utc)
FOLD_COUNT = 10
ENTRY_WINDOW_15M = {
    ScenarioFamily.LIQUIDITY_RAID_REVERSAL: 4,
    ScenarioFamily.TREND_PULLBACK_CONTINUATION: 8,
    ScenarioFamily.RANGE_BOUNDARY_ROTATION: 4,
}
FORBIDDEN = (
    "pnl", "profit_factor", "future_return", "trade_outcome", "mfe", "mae",
    "drawdown", "equity_curve", "target_hit", "stop_hit", "exit_reason",
)


@dataclass(frozen=True)
class ContextView:
    direction: Direction
    regime: ContextRegime
    confidence_0_100: float
    states: Mapping[str, TimeframeContextState]
    conflicts: tuple[str, ...]
    hard_block: bool


@dataclass(frozen=True)
class FamilySpec:
    family: ScenarioFamily
    policy_family: PolicyFamily
    anchor: AnchorEventV1
    poi: POIZone
    source_level: LiquidityLevelV1 | None
    reaction_event: InteractionEventV1
    raid_event: InteractionEventV1 | None
    relation: InteractionRelationV1 | None
    range_state: TimeframeContextState | None


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _assert_no_outcomes(value: Any) -> None:
    raw = json.dumps(_jsonable(value), sort_keys=True).lower()
    for fragment in FORBIDDEN:
        if f'"{fragment}"' in raw:
            raise ValueError(f"forbidden outcome field: {fragment}")


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_locked_dataset(root: Path = DATA_ROOT) -> tuple[dict[str, Any], dict[str, list[Candle]]]:
    manifest_path = root / "p7_full_recognition_data_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("recognition_id") != RECOGNITION_ID:
        raise ValueError("recognition id mismatch")
    if tuple(manifest.get("symbols", ())) != tuple(ALLOWED_SYMBOLS):
        raise ValueError("symbol universe mismatch")
    if manifest.get("archive_count") != 30 or len(manifest.get("archives", ())) != 30:
        raise ValueError("exactly 30 archives are required")
    canonical = manifest.get("canonical_files", {})
    if set(canonical) != set(ALLOWED_SYMBOLS):
        raise ValueError("canonical symbol set mismatch")

    output: dict[str, list[Candle]] = {}
    for symbol in ALLOWED_SYMBOLS:
        meta = canonical[symbol]
        path = root / str(meta["filename"])
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != meta["sha256"]:
            raise ValueError(f"canonical sha mismatch: {symbol}")
        rows: list[Candle] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                candle = Candle(
                    symbol=str(raw["symbol"]).upper(),
                    time=_parse_time(str(raw["time"])),
                    open=float(raw["open"]),
                    high=float(raw["high"]),
                    low=float(raw["low"]),
                    close=float(raw["close"]),
                    volume=float(raw["volume"]),
                )
                if candle.symbol != symbol:
                    raise ValueError(f"symbol mismatch in {path}")
                rows.append(candle)
        rows.sort(key=lambda item: item.time)
        if len(rows) != int(meta["row_count"]):
            raise ValueError(f"row count mismatch: {symbol}")
        if not rows or rows[0].time != START or rows[-1].time != END_OPEN:
            raise ValueError(f"fixed interval mismatch: {symbol}")
        if any(right.time - left.time != timedelta(minutes=5) for left, right in zip(rows, rows[1:])):
            raise ValueError(f"non-5m cadence: {symbol}")
        output[symbol] = rows
    _assert_no_outcomes(manifest)
    return manifest, output


def assign_folds(boundaries: Sequence[datetime], fold_count: int = FOLD_COUNT) -> dict[datetime, int]:
    if fold_count != 10:
        raise ValueError("P7 requires exactly 10 folds")
    ordered = tuple(sorted(boundaries))
    base, remainder = divmod(len(ordered), fold_count)
    output: dict[datetime, int] = {}
    index = 0
    for fold in range(fold_count):
        size = base + (1 if fold < remainder else 0)
        for timestamp in ordered[index : index + size]:
            output[timestamp] = fold
        index += size
    if index != len(ordered) or len(output) != len(ordered):
        raise AssertionError("fold partition is not exact")
    return output


def _atr(rows: Sequence[ClosedBar], length: int = 14) -> float | None:
    if len(rows) < length:
        return None
    sample = rows[-length:]
    values: list[float] = []
    previous: ClosedBar | None = None
    for bar in sample:
        if previous is None:
            values.append(bar.high - bar.low)
        else:
            values.append(max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close)))
        previous = bar
    return sum(values) / len(values)


def _context_view(engine: MtfDealingRangeEngine, symbol: str, timestamp: datetime, cfg: ContextLiquidityConfig) -> ContextView:
    snapshot = engine.snapshot(symbol, timestamp)
    contexts = {
        "1M": snapshot.monthly,
        "1w": snapshot.weekly,
        "1d": snapshot.daily,
        "4h": snapshot.h4,
        "1h": snapshot.h1,
    }
    states = {
        tf: build_timeframe_state(symbol, tf, ctx, engine.bars.get(tf, ()), timestamp, cfg)
        for tf, ctx in contexts.items()
    }
    direction, regime, confidence, conflicts = _aggregate_context(states, cfg)
    return ContextView(direction, regime, confidence, states, conflicts, regime == ContextRegime.INSUFFICIENT)


def _precompute_levels(engine: MtfDealingRangeEngine, symbol: str, boundaries: Sequence[datetime], cfg: ContextLiquidityConfig) -> tuple[LiquidityLevelV1, ...]:
    end = boundaries[-1]
    levels: list[LiquidityLevelV1] = []
    levels.extend(_pivot_liquidity_levels(engine, symbol, end, cfg))
    levels.extend(_equal_liquidity_levels(engine, symbol, end, cfg))
    for timestamp in (bar.close_time for bar in engine.bars["1d"] if bar.symbol == symbol and bar.close_time <= end):
        levels.extend(_period_liquidity_levels(engine, symbol, timestamp))
    session_marks = {(spec.end_minute_utc // 60, spec.end_minute_utc % 60) for spec in cfg.session_specs}
    for timestamp in boundaries:
        if (timestamp.hour, timestamp.minute) in session_marks:
            levels.extend(_session_liquidity_levels(engine, symbol, timestamp, cfg))
    for timestamp in (bar.close_time for bar in engine.bars["4h"] if bar.symbol == symbol and bar.close_time <= end):
        levels.extend(_range_liquidity_levels(_context_view(engine, symbol, timestamp, cfg).states))
    return _deduplicate_levels(level for level in levels if level.confirmed_at <= end)


def _relevant_levels(levels: Sequence[LiquidityLevelV1], bars_5m: Sequence[ClosedBar], recent_15m: Sequence[ClosedBar], timestamp: datetime, cfg: ContextLiquidityConfig) -> tuple[LiquidityLevelV1, ...]:
    if not recent_15m:
        return ()
    recent_low = min(bar.low for bar in recent_15m)
    recent_high = max(bar.high for bar in recent_15m)
    current_atr = _atr(bars_5m, cfg.atr_length) or max(1e-12, bars_5m[-1].close * 0.001)
    source = [level for level in levels if level.confirmed_at <= timestamp and level.high >= recent_low and level.low <= recent_high]
    return tuple(evaluate_liquidity_state(level, bars_5m, timestamp, atr=current_atr, config=cfg) for level in source)


def _select_target(levels: Sequence[LiquidityLevelV1], bars_5m: Sequence[ClosedBar], selected_at: datetime, entry_price: float, side: Direction, cfg: ContextLiquidityConfig) -> tuple[Any | None, LiquidityLevelV1 | None]:
    current_atr = _atr(bars_5m, cfg.atr_length) or max(1e-12, entry_price * 0.001)
    raw = [
        level for level in levels
        if level.confirmed_at <= selected_at
        and ((side == Direction.LONG and level.side == LiquiditySide.BUY_SIDE and level.low > entry_price)
             or (side == Direction.SHORT and level.side == LiquiditySide.SELL_SIDE and level.high < entry_price))
    ]
    raw.sort(key=lambda level: (
        0 if level.external else 1,
        (level.low - entry_price) / entry_price if side == Direction.LONG else (entry_price - level.high) / entry_price,
        -level.strength_0_100,
        level.level_id,
    ))
    for level in raw:
        evaluated = evaluate_liquidity_state(level, bars_5m, selected_at, atr=current_atr, config=cfg)
        candidates = target_candidates((evaluated,), evaluated.symbol, selected_at, entry_price, side)
        if candidates:
            return candidates[0], evaluated
    return None, None


def _active_pois(engine: MtfDealingRangeEngine, timestamp: datetime, poi_engine: POIImbalanceEngine) -> tuple[tuple[POIZone, ...], dict[str, P1EvidenceRecord]]:
    zones: list[POIZone] = []
    evidence: dict[str, P1EvidenceRecord] = {}
    for timeframe in ("1h", "4h"):
        snapshot = poi_engine.detect(engine.bars[timeframe], timestamp)
        zones.extend(zone for zone in snapshot.zones if zone.confirmed_at <= timestamp and zone.state != POIState.INVALIDATED)
        evidence.update({item.evidence_id: item for item in snapshot.evidence if item.confirmed_at <= timestamp})
    return tuple(sorted({zone.poi_id: zone for zone in zones}.values(), key=lambda zone: (zone.confirmed_at, zone.poi_id))), evidence


def _exact_range_overlap(anchor: AnchorEventV1, poi: POIZone, levels: Sequence[LiquidityLevelV1], view: ContextView, bar: ClosedBar | None) -> tuple[LiquidityLevelV1 | None, TimeframeContextState | None]:
    if view.regime != ContextRegime.RANGE or bar is None:
        return None, None
    for state in (view.states.get("4h"), view.states.get("1d")):
        if state is None or state.range_low is None or state.range_high is None:
            continue
        kind = LiquidityKind.RANGE_LOW if anchor.direction == Direction.LONG else LiquidityKind.RANGE_HIGH
        for level in levels:
            if level.kind != kind or level.confirmed_at > anchor.confirmed_at:
                continue
            overlaps = level.high >= poi.low and level.low <= poi.high
            back_inside = bar.close >= state.range_low if anchor.direction == Direction.LONG else bar.close <= state.range_high
            if overlaps and back_inside:
                return level, state
    return None, None


def _family_specs(interaction: Any, pois: Mapping[str, POIZone], levels: Mapping[str, LiquidityLevelV1], view: ContextView, bars_15m: Sequence[ClosedBar]) -> tuple[FamilySpec, ...]:
    events = {event.event_id: event for event in interaction.events}
    relations_by_target: dict[str, list[InteractionRelationV1]] = {}
    for relation in interaction.relations:
        relations_by_target.setdefault(relation.target_event_id, []).append(relation)
    bar_by_close = {bar.close_time: bar for bar in bars_15m}
    output: list[FamilySpec] = []
    for anchor in interaction.anchors:
        if anchor.state != InteractionState.CONFIRMED or anchor.kind != AnchorKind.POI_REJECTION:
            continue
        event = events.get(anchor.event_id)
        poi = pois.get(anchor.source_poi_id or "")
        if event is None or poi is None:
            continue
        for relation in relations_by_target.get(event.event_id, ()):
            if relation.relation != RelationKind.INDUCEMENT_TO_REACTION:
                continue
            raid = events.get(relation.source_id)
            level = levels.get(relation.source_liquidity_id or "")
            if raid is not None and level is not None and raid.kind == InteractionKind.SWEEP:
                output.append(FamilySpec(ScenarioFamily.LIQUIDITY_RAID_REVERSAL, PolicyFamily.RAID_REVERSAL, anchor, poi, level, event, raid, relation, None))
        aligned = view.direction == anchor.direction and (
            (anchor.direction == Direction.LONG and view.regime in {ContextRegime.TREND_UP, ContextRegime.EXPANSION})
            or (anchor.direction == Direction.SHORT and view.regime in {ContextRegime.TREND_DOWN, ContextRegime.EXPANSION})
        )
        if aligned:
            output.append(FamilySpec(ScenarioFamily.TREND_PULLBACK_CONTINUATION, PolicyFamily.TREND_CONTINUATION, anchor, poi, None, event, None, None, None))
        range_level, range_state = _exact_range_overlap(anchor, poi, tuple(levels.values()), view, bar_by_close.get(anchor.confirmed_at))
        if range_level is not None and range_state is not None:
            output.append(FamilySpec(ScenarioFamily.RANGE_BOUNDARY_ROTATION, PolicyFamily.RANGE_ROTATION, anchor, poi, range_level, event, None, None, range_state))
    unique = {(item.family.value, item.anchor.anchor_id, item.poi.poi_id, item.source_level.level_id if item.source_level else ""): item for item in output}
    return tuple(sorted(unique.values(), key=lambda item: (item.anchor.confirmed_at, item.family.value, item.anchor.anchor_id)))


def _entry_geometry(structure: LocalStructureV1, family: ScenarioFamily, bars_15m: Sequence[ClosedBar], timestamp: datetime) -> tuple[float, datetime] | None:
    if structure.state != ExecutionState.CONFIRMED or structure.confirmed_at is None:
        return None
    after = [bar for bar in bars_15m if bar.open_time >= structure.confirmed_at and bar.close_time <= timestamp][:ENTRY_WINDOW_15M[family]]
    if family in {ScenarioFamily.LIQUIDITY_RAID_REVERSAL, ScenarioFamily.RANGE_BOUNDARY_ROTATION}:
        if not after:
            return None
        first = after[0]
        return (first.open, first.close_time) if timestamp == first.close_time else None
    for bar in after:
        touched = bar.low <= structure.boundary <= bar.high
        held = bar.close >= structure.boundary if structure.direction == Direction.LONG else bar.close <= structure.boundary
        if touched and held:
            return (structure.boundary, bar.close_time) if timestamp == bar.close_time else None
    return None


def _p1_evidence_for_node(poi: POIZone, evidence_map: Mapping[str, P1EvidenceRecord], node: str) -> list[EvidenceInput]:
    relation_map = {
        P1EvidenceRelation.PRIMARY: EvidenceRelation.PRIMARY,
        P1EvidenceRelation.DERIVED: EvidenceRelation.DERIVED,
        P1EvidenceRelation.INDEPENDENT: EvidenceRelation.CORROBORATING,
        P1EvidenceRelation.CONFLICTING: EvidenceRelation.CONFLICTING,
    }
    output: list[EvidenceInput] = []
    for evidence_id in poi.evidence_ids:
        source = evidence_map.get(evidence_id)
        if source is not None:
            output.append(EvidenceInput(source.evidence_id, source.cluster_id, node, relation_map[source.relation], source.strength_0_100, source.confirmed_at))
    return output


def _primary_evidence(node: str, source_id: str, strength: float, confirmed_at: datetime) -> EvidenceInput:
    return EvidenceInput(_stable_id("adapter_ev", node, source_id), _stable_id("adapter_cluster", source_id), node, EvidenceRelation.PRIMARY, max(0.0, min(100.0, strength)), confirmed_at)


def _base_family_evidence(spec: FamilySpec, view: ContextView, structure: LocalStructureV1, target_level: LiquidityLevelV1, evidence_map: Mapping[str, P1EvidenceRecord]) -> list[EvidenceInput]:
    evidence: list[EvidenceInput] = []
    context_id = _stable_id("context", spec.poi.symbol, view.regime.value, view.direction.value, spec.anchor.confirmed_at.isoformat())
    if spec.family == ScenarioFamily.LIQUIDITY_RAID_REVERSAL:
        evidence.append(_primary_evidence("location", context_id, view.confidence_0_100, spec.anchor.confirmed_at))
        evidence.append(_primary_evidence("raid", spec.raid_event.event_id, spec.raid_event.strength_0_100, spec.raid_event.confirmed_at))
        evidence.extend(_p1_evidence_for_node(spec.poi, evidence_map, "poi"))
        evidence.append(_primary_evidence("return_acceptance", spec.reaction_event.event_id, spec.reaction_event.strength_0_100, spec.reaction_event.confirmed_at))
        evidence.append(_primary_evidence("structure", structure.structure_id, structure.confidence_0_100, structure.confirmed_at or structure.evaluated_at))
    elif spec.family == ScenarioFamily.TREND_PULLBACK_CONTINUATION:
        evidence.append(_primary_evidence("trend", context_id, view.confidence_0_100, spec.anchor.confirmed_at))
        evidence.extend(_p1_evidence_for_node(spec.poi, evidence_map, "poi"))
        matching = [state.confidence_0_100 for state in view.states.values() if state.direction == spec.anchor.direction and state.protected_level is not None]
        evidence.append(_primary_evidence("htf_protection", context_id + ":protection", max(matching, default=0.0), spec.anchor.confirmed_at))
        evidence.append(_primary_evidence("mitigation", spec.reaction_event.event_id, spec.reaction_event.strength_0_100, spec.reaction_event.confirmed_at))
        evidence.append(_primary_evidence("resumption", structure.structure_id, structure.confidence_0_100, structure.confirmed_at or structure.evaluated_at))
    else:
        evidence.append(_primary_evidence("range", context_id, view.confidence_0_100, spec.anchor.confirmed_at))
        evidence.append(_primary_evidence("boundary_liquidity", spec.source_level.level_id, spec.source_level.strength_0_100, spec.source_level.confirmed_at))
        evidence.extend(_p1_evidence_for_node(spec.poi, evidence_map, "poi_rejection"))
        evidence.append(_primary_evidence("acceptance", spec.reaction_event.event_id, spec.reaction_event.strength_0_100, spec.reaction_event.confirmed_at))
        evidence.append(_primary_evidence("space", target_level.level_id, target_level.strength_0_100, target_level.confirmed_at))
    return evidence


def _build_observation(symbol: str, fold: int, timestamp: datetime, spec: FamilySpec, view: ContextView, structure: LocalStructureV1, entry_price: float, target: Any, target_level: LiquidityLevelV1, bars_15m: Sequence[ClosedBar], evidence_map: Mapping[str, P1EvidenceRecord]) -> RecognitionObservation | None:
    if structure.protected_swing <= 0 or entry_price <= 0:
        return None
    costs = CostModel()
    buffer_fraction = costs.cost_buffer_pct / 100.0
    if spec.anchor.direction == Direction.LONG:
        stop_price = structure.protected_swing * (1.0 - buffer_fraction)
        liquidation_price = entry_price * 0.95
        if not stop_price < entry_price < target.price:
            return None
        risk_side = RiskSide.LONG
        fusion_side = "LONG"
    else:
        stop_price = structure.protected_swing * (1.0 + buffer_fraction)
        liquidation_price = entry_price * 1.05
        if not target.price < entry_price < stop_price:
            return None
        risk_side = RiskSide.SHORT
        fusion_side = "SHORT"
    closed_15m = [bar for bar in bars_15m if bar.close_time <= timestamp]
    atr_value = _atr(closed_15m, 14) or max(1e-12, entry_price * 0.001)
    atr_floor_pct = atr_value / entry_price * 100.0
    width_pct = max(0.0, target_level.high - target_level.low) / entry_price * 100.0
    liquidity_buffer_pct = max(width_pct, ContextLiquidityConfig().level_buffer_atr * atr_floor_pct)
    base_evidence = _base_family_evidence(spec, view, structure, target_level, evidence_map)
    preliminary_input = FusionInput(
        symbol=symbol,
        side=fusion_side,
        family=spec.family,
        evaluated_at=timestamp,
        target_level_id=target_level.level_id,
        poi_id=spec.poi.poi_id,
        anchor_id=spec.anchor.anchor_id,
        structure_id=structure.structure_id,
        protected_swing_id=_stable_id("protected", structure.structure_id, round(structure.protected_swing, 12)),
        poi_lifecycle_id=f"{spec.poi.poi_id}:{spec.poi.state.value}:{spec.poi.test_count}",
        discovered=True,
        armed=True,
        reaction_detected=True,
        structure_confirmed=True,
        economics_valid=False,
        risk_valid=False,
        hard_blocks=(),
        critical_conflicts=tuple(view.conflicts + structure.conflicts),
    )
    preliminary = fuse_scenario(preliminary_input, base_evidence)
    candidate = ExecutionCandidate(
        candidate_id=preliminary.scenario.scenario_id,
        symbol=symbol,
        side=risk_side,
        evaluated_at=timestamp.isoformat(),
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target.price,
        atr_floor_pct=atr_floor_pct,
        liquidity_buffer_pct=liquidity_buffer_pct,
        upstream_score=preliminary.scenario.total_score_0_100,
        dependency_ids=(target.target_id, target_level.level_id, spec.poi.poi_id, spec.anchor.anchor_id, structure.structure_id),
        dependencies_causal=True,
        leverage=20.0,
        margin_mode="isolated",
        liquidation_price=liquidation_price,
        correlation_cluster="CRYPTO_MARKET_BETA",
    )
    admission = evaluate_candidate(candidate, AccountState(equity=10000.0))
    economics_valid = admission.decision in {AdmissionDecision.PASS, AdmissionDecision.CONDITIONAL_PASS}
    risk_valid = economics_valid
    economics_cancelled = admission.decision == AdmissionDecision.REJECT_ECONOMICS
    risk_cancelled = admission.decision == AdmissionDecision.REJECT_RISK
    final_evidence = list(base_evidence)
    final_evidence.append(_primary_evidence("economics", admission.evaluation_id + ":economics", 100.0 if economics_valid else 0.0, timestamp))
    final_evidence.append(_primary_evidence("risk", admission.evaluation_id + ":risk", 100.0 if risk_valid else 0.0, timestamp))
    hard_blocks: list[str] = []
    if economics_cancelled:
        hard_blocks.extend(f"economics:{reason}" for reason in admission.reasons)
    if risk_cancelled:
        hard_blocks.extend(f"risk:{reason}" for reason in admission.reasons)
    final_input = FusionInput(
        symbol=preliminary_input.symbol,
        side=preliminary_input.side,
        family=preliminary_input.family,
        evaluated_at=preliminary_input.evaluated_at,
        target_level_id=preliminary_input.target_level_id,
        poi_id=preliminary_input.poi_id,
        anchor_id=preliminary_input.anchor_id,
        structure_id=preliminary_input.structure_id,
        protected_swing_id=preliminary_input.protected_swing_id,
        poi_lifecycle_id=preliminary_input.poi_lifecycle_id,
        discovered=True,
        armed=True,
        reaction_detected=True,
        structure_confirmed=True,
        economics_valid=economics_valid,
        risk_valid=risk_valid,
        economics_cancelled=economics_cancelled,
        risk_cancelled=risk_cancelled,
        hard_blocks=tuple(hard_blocks),
        critical_conflicts=preliminary_input.critical_conflicts,
    )
    final = fuse_scenario(final_input, final_evidence)
    scenario = final.scenario
    interaction_ids = tuple(sorted({spec.reaction_event.event_id, *([spec.raid_event.event_id] if spec.raid_event else []), *([spec.relation.relation_id] if spec.relation else [])}))
    liquidity_ids = tuple(sorted({target_level.level_id, *([spec.source_level.level_id] if spec.source_level else [])}))
    return RecognitionObservation(
        symbol=symbol,
        direction=spec.anchor.direction.value,
        fold=fold,
        timestamp=timestamp,
        family=spec.family.value,
        decision=final.decision.value,
        lifecycle=scenario.state.value,
        fingerprint=scenario.fingerprint,
        rearm_parent=None,
        poi_id=spec.poi.poi_id,
        liquidity_ids=liquidity_ids,
        interaction_ids=interaction_ids,
        anchor_id=spec.anchor.anchor_id,
        structure_id=structure.structure_id,
        evidence_ids=scenario.evidence_ids,
        evidence_cluster_ids=scenario.evidence_cluster_ids,
        economics_valid=economics_valid,
        risk_valid=risk_valid,
        block_reasons=tuple(admission.reasons) + tuple(final.reasons),
        hard_blocks=tuple(hard_blocks),
    )


def scan_symbol(symbol: str, candles: Sequence[Candle]) -> tuple[list[RecognitionObservation], dict[str, Any]]:
    engine = MtfDealingRangeEngine(candles)
    bars_5m_all = [bar for bar in engine.bars["5m"] if bar.symbol == symbol]
    bars_15m_all = [bar for bar in engine.bars["15m"] if bar.symbol == symbol]
    boundaries = [bar.close_time for bar in bars_15m_all]
    folds = assign_folds(boundaries)
    context_cfg = ContextLiquidityConfig()
    interaction_cfg = InteractionConfig()
    interaction_engine = InteractionEngineV1(interaction_cfg)
    poi_engine = POIImbalanceEngine()
    levels_all = _precompute_levels(engine, symbol, boundaries, context_cfg)
    context_cache: dict[datetime, ContextView] = {}
    poi_cache: dict[datetime, tuple[tuple[POIZone, ...], dict[str, P1EvidenceRecord]]] = {}
    observations: list[RecognitionObservation] = []
    diagnostics = {"symbol": symbol, "boundaries": len(boundaries), "anchors_seen": 0, "family_specs": 0, "entry_geometries": 0, "observations": 0, "raw_levels": len(levels_all)}
    bars_5m: list[ClosedBar] = []
    bars_15m: list[ClosedBar] = []
    cursor_5m = 0
    for current_15m in bars_15m_all:
        timestamp = current_15m.close_time
        while cursor_5m < len(bars_5m_all) and bars_5m_all[cursor_5m].close_time <= timestamp:
            bars_5m.append(bars_5m_all[cursor_5m])
            cursor_5m += 1
        bars_15m.append(current_15m)
        cache_key = timestamp.replace(minute=0, second=0, microsecond=0)
        if cache_key not in context_cache:
            context_cache[cache_key] = _context_view(engine, symbol, timestamp, context_cfg)
        view = context_cache[cache_key]
        if cache_key not in poi_cache:
            poi_cache[cache_key] = _active_pois(engine, timestamp, poi_engine)
        pois, evidence_map = poi_cache[cache_key]
        if view.hard_block or not pois:
            continue
        lookback = interaction_cfg.atr_length + max(interaction_cfg.inducement_max_age_bars, interaction_cfg.anchor_expiry_bars, interaction_cfg.acceptance_closes, interaction_cfg.invalidation_closes) + 2
        recent_15m = bars_15m[-lookback:]
        relevant_levels = _relevant_levels(levels_all, bars_5m, recent_15m, timestamp, context_cfg)
        relevant_pois = tuple(poi for poi in pois if any(bar.high >= poi.low and bar.low <= poi.high for bar in recent_15m))
        if not relevant_levels and not relevant_pois:
            continue
        interaction = interaction_engine.snapshot(symbol=symbol, timeframe="15m", bars=recent_15m, pois=relevant_pois, levels=relevant_levels, evaluated_at=timestamp)
        diagnostics["anchors_seen"] += len(interaction.anchors)
        specs = _family_specs(interaction, {poi.poi_id: poi for poi in relevant_pois}, {level.level_id: level for level in relevant_levels}, view, recent_15m)
        diagnostics["family_specs"] += len(specs)
        for spec in specs:
            structure = evaluate_execution_structure(
                spec.anchor,
                {"5m": [bar for bar in bars_5m if bar.close_time >= spec.anchor.confirmed_at], "15m": [bar for bar in bars_15m if bar.close_time >= spec.anchor.confirmed_at]},
                timestamp,
            )
            if not apply_family_policy(structure, spec.policy_family).allowed:
                continue
            geometry = _entry_geometry(structure, spec.family, bars_15m, timestamp)
            if geometry is None:
                continue
            entry_price, entry_timestamp = geometry
            diagnostics["entry_geometries"] += 1
            target, target_level = _select_target(levels_all, bars_5m, spec.anchor.confirmed_at, entry_price, spec.anchor.direction, context_cfg)
            if target is None or target_level is None:
                continue
            observation = _build_observation(symbol, folds[timestamp], entry_timestamp, spec, view, structure, entry_price, target, target_level, bars_15m, evidence_map)
            if observation is not None:
                observations.append(observation)
    diagnostics["observations"] = len(observations)
    return observations, diagnostics


def execute_full_recognition(root: Path = DATA_ROOT) -> dict[str, Any]:
    manifest, candles_by_symbol = load_locked_dataset(root)
    all_rows: list[RecognitionObservation] = []
    diagnostics: list[dict[str, Any]] = []
    for symbol in ALLOWED_SYMBOLS:
        rows, diag = scan_symbol(symbol, candles_by_symbol[symbol])
        all_rows.extend(rows)
        diagnostics.append(diag)
    report = run_full_recognition(all_rows)
    deduped, _ = dedupe_global(all_rows)
    counted_rows = tuple(row for row in deduped if is_counted(row))
    payload = {
        "recognition_id": RECOGNITION_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_1",
        "data_manifest_sha256": hashlib.sha256((root / "p7_full_recognition_data_manifest_v1.json").read_bytes()).hexdigest(),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"],
        "end_inclusive": manifest["end_inclusive"],
        "fold_count": 10,
        "status": "PASS" if report.gate_pass else "FAIL",
        "recognition": report_to_no_outcome_dict(report),
        "by_family": {family.value: sum(row.family == family.value for row in counted_rows) for family in ScenarioFamily},
        "diagnostics": diagnostics,
    }
    _assert_no_outcomes(payload)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    payload = execute_full_recognition()
    print(json.dumps({
        "recognition_id": payload["recognition_id"],
        "status": payload["status"],
        "independent_entry_ready": payload["recognition"]["independent_entry_ready"],
        "gate_pass": payload["recognition"]["gate_pass"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
