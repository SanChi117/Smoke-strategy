#!/usr/bin/env python3
"""Strict out-of-sample evaluation for walk-forward folds.

The research pipeline needs warm-up candles and warm-up trades so causal Quality,
Structure Learning and rolling-universe layers have history. Those warm-up trades
must never contribute to the reported fold P&L.

This module reuses the decisions learned on the full warm-up + validation dataset,
but sends only candidates whose entry belongs to the validation interval into the
portfolio simulator. Simultaneous candidates are ranked using entry-time facts
only; symbol alphabet order is never used as a quality proxy.

Research/paper only. No API keys. No order execution.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from strategy_lab.config import PipelineConfig, get_risk_profile
from strategy_lab.portfolio_simulator import simulate_dynamic_portfolio
from strategy_lab.rolling_symbol_strength import CostConfig, load_trades_csv
from strategy_lab.schemas import PipelineSummary
from strategy_lab.validation import write_validation_report


def parse_dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def bool_value(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def reason_values(text: object) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in str(text or "").split("|"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        out[key.strip().lower()] = value.strip().lower()
    return out


def causal_priority(decision: dict[str, str], generated: dict[str, str]) -> float:
    """Entry-time ranking score with no outcome-derived fields.

    Components are intentionally generic: original confidence, current causal
    TAKE/WATCH states, candle-plan quality, volume participation and higher-timeframe
    alignment. No symbol, realised R, exit price or future result is used.
    """

    meta = reason_values(generated.get("risk_plan_reason"))
    score = safe_float(generated.get("confidence_hint"), 0.0)
    if str(decision.get("quality_decision", "")).upper() == "TAKE":
        score += 5.0
    if str(decision.get("structure_decision", "")).upper() == "TAKE":
        score += 5.0
    score += min(100.0, max(0.0, safe_float(meta.get("quality"), 0.0))) * 0.05
    score += min(3.0, max(0.0, safe_float(meta.get("vr"), 0.0)))
    alignment = meta.get("ctx_align", "")
    if alignment == "full_align":
        score += 2.0
    elif alignment in {"h4_only", "d1_only"}:
        score += 1.0
    return round(score, 6)


def read_csv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str | Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    if not fields:
        p.write_text("", encoding="utf-8")
        return
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def trade_key(symbol: object, side: object, entry_time: object) -> tuple[str, str, datetime]:
    return (str(symbol).strip().upper(), str(side).strip().lower(), parse_dt(entry_time))


def evaluate_validation_window(
    run_dir: str | Path,
    validation_start: datetime,
    validation_end: datetime,
    profile_name: str,
    cfg: PipelineConfig,
) -> PipelineSummary:
    """Recalculate fold metrics using validation entries only."""

    root = Path(run_dir)
    generated_path = root / "generated_trades.csv"
    decisions_path = root / "pipeline_decisions.csv"
    generated_rows = read_csv(generated_path)
    decision_rows = read_csv(decisions_path)

    generated_by_key = {
        trade_key(row.get("symbol"), row.get("side"), row.get("entry_time")): row
        for row in generated_rows
    }
    all_trades = load_trades_csv(generated_path)
    trade_by_key = {
        trade_key(t.symbol, t.side, t.entry_time): t
        for t in all_trades
    }

    validation_decisions = [
        row for row in decision_rows
        if validation_start <= parse_dt(row.get("entry_time")) < validation_end
    ]
    allowed_decisions = [row for row in validation_decisions if bool_value(row.get("allowed"))]

    allowed_trades = []
    risk_pcts: dict[tuple[str, str, object], float] = {}
    priority_scores: dict[tuple[str, str, object], float] = {}
    priority_rows: list[dict[str, object]] = []
    allowed_generated_rows: list[dict[str, object]] = []
    missing: list[str] = []
    for decision in allowed_decisions:
        key = trade_key(decision.get("symbol"), decision.get("side"), decision.get("entry_time"))
        trade = trade_by_key.get(key)
        generated = generated_by_key.get(key)
        if trade is None or generated is None:
            missing.append("|".join([key[0], key[1], key[2].isoformat()]))
            continue
        score = causal_priority(decision, generated)
        allowed_trades.append(trade)
        simulator_key = (trade.symbol.upper(), trade.side.lower(), trade.entry_time)
        risk_pcts[simulator_key] = float(decision.get("risk_pct") or 0.0)
        priority_scores[simulator_key] = score
        priority_rows.append({
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_time": trade.entry_time.isoformat(),
            "priority_score": score,
            "quality_decision": decision.get("quality_decision", ""),
            "structure_decision": decision.get("structure_decision", ""),
            "confidence_hint": generated.get("confidence_hint", ""),
            "risk_plan_reason": generated.get("risk_plan_reason", ""),
        })
        allowed_generated_rows.append(generated)

    profile = get_risk_profile(profile_name)
    cost = CostConfig(fee_rate=cfg.fee_rate, slippage_rate=cfg.slippage_rate)
    result = simulate_dynamic_portfolio(
        allowed_trades,
        risk_pcts,
        profile,
        cost,
        f"{cfg.name}_{profile.name}_STRICT_OOS_PRIORITY",
        priority_scores=priority_scores,
    )

    summary = PipelineSummary(
        profile=profile.name,
        initial_cash=profile.initial_cash,
        leverage=profile.leverage,
        base_risk_pct=profile.base_risk_pct,
        max_risk_pct=profile.max_risk_pct,
        candidates=len(validation_decisions),
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

    generated_fields = list(generated_rows[0].keys()) if generated_rows else []
    decision_fields = list(decision_rows[0].keys()) if decision_rows else []
    write_csv(root / "pipeline_decisions_with_warmup.csv", decision_rows, decision_fields)
    write_csv(root / "pipeline_decisions.csv", validation_decisions, decision_fields)
    write_csv(root / "pipeline_allowed_trades.csv", allowed_generated_rows, generated_fields)
    write_csv(root / "walk_forward_candidate_priorities.csv", priority_rows)
    write_csv(root / "pipeline_summary.csv", [asdict(summary)])
    metadata = {
        "mode": "STRICT_OUT_OF_SAMPLE_PRIORITY",
        "validation_start": validation_start.isoformat(),
        "validation_end": validation_end.isoformat(),
        "warmup_candidates_excluded_from_pnl": len(decision_rows) - len(validation_decisions),
        "validation_candidates": len(validation_decisions),
        "validation_allowed_candidates": len(allowed_trades),
        "priority_mode": "causal_entry_quality",
        "missing_join_keys": missing,
    }
    (root / "walk_forward_evaluation_window.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_validation_report(root)
    return summary
