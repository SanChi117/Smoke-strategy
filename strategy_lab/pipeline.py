#!/usr/bin/env python3
"""Executable research pipeline skeleton for Smoke Strategy Lab.

This is the main integration point. New modules should be attached here rather
than tested as isolated scripts.

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from strategy_lab.config import PipelineConfig, get_risk_profile
from strategy_lab.portfolio_simulator import simulate_dynamic_portfolio
from strategy_lab.risk_diagnostics import build_risk_diagnostics, build_risk_policy_notes, rows_as_dicts as diagnostic_rows_as_dicts
from strategy_lab.rolling_symbol_strength import (
    CostConfig,
    RollingConfig,
    build_rolling_trades,
    load_trades_csv,
)
from strategy_lab.schemas import PipelineDecision, PipelineSummary
from strategy_lab.structure_learning import (
    StructureLearningConfig,
    read_trade_rows as read_structure_rows,
    score_structure_trades,
)
from strategy_lab.trade_quality_score import (
    QualityConfig,
    read_trade_rows as read_quality_rows,
    score_trades as score_quality_trades,
)
from strategy_lab.universe_selector import UniverseConfig, allowed_symbols, rank_universe, rows_as_dicts
from strategy_lab.validation import write_validation_report


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def trade_key(symbol: str, side: str, entry_time: str | datetime) -> tuple[str, str, datetime]:
    return (symbol.upper(), side.lower(), parse_dt(entry_time))


def norm_set(values: tuple[str, ...]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def extract_reason_value(reason: object, key: str) -> str:
    text = str(reason or "")
    match = re.search(rf"(?:^|\|){re.escape(key)}=([^|]+)", text)
    return match.group(1).strip().lower() if match else ""


def extract_reason_float(reason: object, key: str, default: float = 0.0) -> float:
    value = extract_reason_value(reason, key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_trade_metadata(path: str | Path) -> dict[tuple[str, str, datetime], dict[str, str]]:
    """Keep original generated_trades.csv metadata lost by load_trades_csv.

    The lightweight Trade dataclass used by older modules intentionally keeps
    only execution fields, so tactical micro-filters must read risk_plan_reason
    from the original CSV rows and join by symbol/side/entry_time.
    """
    meta: dict[tuple[str, str, datetime], dict[str, str]] = {}
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = trade_key(row.get("symbol", ""), row.get("side", ""), row.get("entry_time", ""))
            meta[key] = row
    return meta


def write_dict_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_pipeline(input_csv: str | Path, out_dir: str | Path = "results", cfg: PipelineConfig | None = None, profile_name: str | None = None) -> PipelineSummary:
    cfg = cfg or PipelineConfig()
    profile = get_risk_profile(profile_name or cfg.default_profile)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cost = CostConfig(fee_rate=cfg.fee_rate, slippage_rate=cfg.slippage_rate)

    all_trades = load_trades_csv(input_csv)
    trade_by_key = {trade_key(t.symbol, t.side, t.entry_time): t for t in all_trades}
    metadata_by_key = read_trade_metadata(input_csv)

    universe_rows = rank_universe(all_trades, UniverseConfig(allow_top_n=9999))
    learned_universe_allowed = allowed_symbols(universe_rows, UniverseConfig(allow_top_n=9999))
    cfg_allowed_symbols = {symbol.upper() for symbol in cfg.allowed_symbols}
    cfg_blocked_symbols = {symbol.upper() for symbol in cfg.blocked_symbols}
    if cfg_allowed_symbols:
        learned_universe_allowed = learned_universe_allowed.intersection(cfg_allowed_symbols)
    if cfg_blocked_symbols:
        learned_universe_allowed = {symbol for symbol in learned_universe_allowed if symbol not in cfg_blocked_symbols}
    write_dict_csv(out / "pipeline_universe_ranking.csv", rows_as_dicts(universe_rows))

    rolling_trades, _windows, _avg_selected = build_rolling_trades(
        all_trades,
        parse_dt(cfg.start),
        parse_dt(cfg.end),
        RollingConfig(cfg.rolling_lookback_days, cfg.rolling_rebalance_days, cfg.rolling_top_n),
        cost,
    )
    rolling_keys = {trade_key(t.symbol, t.side, t.entry_time) for t in rolling_trades}

    quality_cfg = QualityConfig(
        lookback_days=cfg.quality_lookback_days,
        take_threshold=cfg.quality_take_threshold,
        watch_threshold=cfg.quality_watch_threshold,
    )
    quality_rows = score_quality_trades(read_quality_rows(input_csv), quality_cfg)
    quality_by_key = {trade_key(r.symbol, r.side, r.entry_time): r for r in quality_rows}

    structure_cfg = StructureLearningConfig(
        lookback_days=cfg.structure_lookback_days,
        take_threshold=cfg.structure_take_threshold,
        watch_threshold=cfg.structure_watch_threshold,
    )
    structure_rows = score_structure_trades(read_structure_rows(input_csv), structure_cfg)
    structure_by_key = {trade_key(r.symbol, r.side, r.entry_time): r for r in structure_rows}

    allowed_setups = norm_set(cfg.allowed_setup_types)
    blocked_setups = norm_set(cfg.blocked_setup_types)
    allowed_trends = norm_set(cfg.allowed_trend_contexts)
    blocked_trends = norm_set(cfg.blocked_trend_contexts)
    allowed_vols = norm_set(cfg.allowed_volatility_regimes)
    blocked_vols = norm_set(cfg.blocked_volatility_regimes)
    allowed_liq = norm_set(cfg.allowed_liquidity_states)
    blocked_liq = norm_set(cfg.blocked_liquidity_states)
    allowed_candles = norm_set(cfg.allowed_candle_types)
    blocked_candles = norm_set(cfg.blocked_candle_types)
    allowed_dirs = norm_set(cfg.allowed_direction_contexts)
    blocked_dirs = norm_set(cfg.blocked_direction_contexts)

    decisions: list[PipelineDecision] = []
    allowed_trades = []
    risk_pcts: dict[tuple[str, str, object], float] = {}

    for key, trade in sorted(trade_by_key.items(), key=lambda item: (item[1].entry_time, item[1].symbol, item[1].side)):
        q = quality_by_key[key]
        s = structure_by_key[key]
        meta = metadata_by_key.get(key, {})
        reason_text = meta.get("risk_plan_reason") or meta.get("reason") or ""
        setup_type = str(getattr(s, "setup_type", "unknown") or "unknown").strip().lower()
        trend_context = str(getattr(s, "trend_context", "unknown") or "unknown").strip().lower()
        volatility_regime = str(getattr(s, "volatility_regime", "unknown") or "unknown").strip().lower()
        liquidity_state = extract_reason_value(reason_text, "liq")
        candle_type = extract_reason_value(reason_text, "candle")
        direction_context = extract_reason_value(reason_text, "dir")
        volume_ratio = extract_reason_float(reason_text, "vr", 0.0)

        symbol_whitelist_ok = not cfg_allowed_symbols or trade.symbol in cfg_allowed_symbols
        symbol_block_ok = trade.symbol not in cfg_blocked_symbols
        learned_universe_ok = True if not cfg.require_universe_gate else trade.symbol in learned_universe_allowed
        in_universe = symbol_whitelist_ok and symbol_block_ok and learned_universe_ok
        in_rolling = True if not cfg.require_rolling_top else key in rolling_keys
        quality_ok = q.decision != "SKIP"
        structure_ok = s.structure_decision != "SKIP"
        setup_ok = (not allowed_setups or setup_type in allowed_setups) and setup_type not in blocked_setups
        trend_ok = (not allowed_trends or trend_context in allowed_trends) and trend_context not in blocked_trends
        volatility_ok = (not allowed_vols or volatility_regime in allowed_vols) and volatility_regime not in blocked_vols
        liquidity_ok = (not allowed_liq or liquidity_state in allowed_liq) and liquidity_state not in blocked_liq
        candle_ok = (not allowed_candles or candle_type in allowed_candles) and candle_type not in blocked_candles
        direction_ok = (not allowed_dirs or direction_context in allowed_dirs) and direction_context not in blocked_dirs
        volume_ratio_ok = volume_ratio >= cfg.min_volume_ratio
        allowed = (
            in_universe
            and in_rolling
            and quality_ok
            and structure_ok
            and setup_ok
            and trend_ok
            and volatility_ok
            and liquidity_ok
            and candle_ok
            and direction_ok
            and volume_ratio_ok
        )

        if not symbol_whitelist_ok:
            reason = "symbol_not_in_explicit_allowlist"
        elif not symbol_block_ok:
            reason = "symbol_blocked_explicitly"
        elif not learned_universe_ok:
            reason = "symbol_not_allowed_by_universe"
        elif not in_rolling:
            reason = "not_in_current_rolling_top"
        elif not quality_ok:
            reason = "quality_skip"
        elif not structure_ok:
            reason = "structure_skip"
        elif not setup_ok:
            reason = "setup_filtered"
        elif not trend_ok:
            reason = "trend_context_filtered"
        elif not volatility_ok:
            reason = "volatility_regime_filtered"
        elif not liquidity_ok:
            reason = "liquidity_state_filtered"
        elif not candle_ok:
            reason = "candle_type_filtered"
        elif not direction_ok:
            reason = "direction_context_filtered"
        elif not volume_ratio_ok:
            reason = "volume_ratio_filtered"
        else:
            reason = "allowed_full_balanced"

        if q.decision == "TAKE" and s.structure_decision == "TAKE":
            risk_pct = min(profile.max_risk_pct, profile.base_risk_pct * profile.take_risk_multiplier)
        elif allowed:
            risk_pct = min(profile.max_risk_pct, profile.base_risk_pct * profile.watch_risk_multiplier)
        else:
            risk_pct = 0.0

        decisions.append(PipelineDecision(
            symbol=trade.symbol,
            side=trade.side,
            entry_time=trade.entry_time,
            allowed=allowed,
            reason=reason,
            universe_state="allowed" if in_universe else "blocked",
            quality_decision=q.decision,
            structure_decision=s.structure_decision,
            risk_pct=round(risk_pct, 6),
            leverage=profile.leverage,
            target_policy=s.recommended_target_policy,
            setup_type=setup_type,
            trend_context=trend_context,
            volatility_regime=volatility_regime,
        ))
        if allowed:
            allowed_trades.append(trade)
            risk_pcts[key] = risk_pct

    write_dict_csv(out / "pipeline_decisions.csv", [asdict(row) for row in decisions])
    write_dict_csv(out / "pipeline_risk_diagnostics.csv", diagnostic_rows_as_dicts(build_risk_diagnostics(decisions)))
    write_dict_csv(out / "pipeline_risk_policy.csv", diagnostic_rows_as_dicts(build_risk_policy_notes()))

    result = simulate_dynamic_portfolio(
        allowed_trades,
        risk_pcts,
        profile,
        cost,
        f"{cfg.name}_{profile.name}",
    )
    summary = PipelineSummary(
        profile=profile.name,
        initial_cash=profile.initial_cash,
        leverage=profile.leverage,
        base_risk_pct=profile.base_risk_pct,
        max_risk_pct=profile.max_risk_pct,
        candidates=len(all_trades),
        allowed_candidates=len(allowed_trades),
        executed_trades=result.trades,
        skipped=result.skipped,
        skipped_no_risk=result.skipped_no_risk,
        skipped_max_positions=result.skipped_max_positions,
        skipped_symbol_limit=result.skipped_symbol_limit,
        skipped_cash=result.skipped_cash,
        skipped_daily_halt=result.skipped_daily_halt,
        skipped_weekly_halt=result.skipped_weekly_halt,
        final_cash=round(result.final_cash, 2),
        ret_pct=round(result.ret_pct, 2),
        max_dd_pct=round(result.max_dd_pct, 2),
        pf=round(result.pf, 4),
        winrate=round(result.winrate, 2),
        max_loss_streak=result.max_loss_streak,
        symbols_traded=result.symbols_traded,
        symbols_positive=result.symbols_positive,
        total_fees=round(result.total_fees, 4),
        avg_risk_pct=round(result.avg_risk_pct, 6),
    )
    write_dict_csv(out / "pipeline_summary.csv", [asdict(summary)])
    write_validation_report(out)
    return summary


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--profile", default="growth_100_20x")
    args = p.parse_args()

    summary = run_pipeline(args.input, args.out_dir, profile_name=args.profile)
    print("Smoke pipeline complete")
    print(f"Profile: {summary.profile}")
    print(f"Candidates: {summary.candidates}")
    print(f"Allowed candidates: {summary.allowed_candidates}")
    print(f"Executed trades: {summary.executed_trades}")
    print(f"Skipped: {summary.skipped}")
    print(f"Final cash: {summary.final_cash}")
    print(f"Return: {summary.ret_pct}%")
    print(f"DD: {summary.max_dd_pct}%")
    print(f"PF: {summary.pf}")
    print(f"Winrate: {summary.winrate}%")
    print(f"Avg risk pct: {summary.avg_risk_pct}")


if __name__ == "__main__":
    main()
