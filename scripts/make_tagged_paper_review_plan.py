#!/usr/bin/env python3
"""Create a paper-review plan for the tagged MTF candidate.

Research artifact only. No exchange API. No order execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def deep_stats(deep: dict[str, Any]) -> dict[str, Any]:
    stats = deep.get("deep_validation") if isinstance(deep.get("deep_validation"), dict) else deep
    return stats if isinstance(stats, dict) else {}


def verdict(decision: dict[str, Any], deep: dict[str, Any], multi: dict[str, Any]) -> tuple[str, list[str]]:
    stats = deep_stats(deep)
    reasons: list[str] = []
    tagged_decision = str(decision.get("decision", ""))
    deep_decision = str(deep.get("decision", ""))
    multi_verdict = str(multi.get("wfo_verdict", ""))
    deep_pf = float(stats.get("avg_pf", 0) or 0)
    deep_ret = float(stats.get("avg_ret_pct", 0) or 0)
    deep_pos = int(float(stats.get("positive_folds", 0) or 0))
    deep_valid = int(float(stats.get("valid_folds", stats.get("folds", 0)) or 0))
    deep_dd = float(stats.get("worst_max_dd_pct", 99) or 99)
    trades = int(float(stats.get("total_executed_trades", 0) or 0))

    reasons.append(f"tagged_decision={tagged_decision}")
    reasons.append(f"deep_decision={deep_decision}")
    reasons.append(f"multi_wfo_verdict={multi_verdict}")
    reasons.append(f"deep_folds={deep_pos}/{deep_valid}")
    reasons.append(f"deep_avg_pf={deep_pf}")
    reasons.append(f"deep_avg_ret_pct={deep_ret}")
    reasons.append(f"deep_worst_dd_pct={deep_dd}")
    reasons.append(f"deep_trades={trades}")

    if tagged_decision == "PROMOTE_TO_PAPER_REVIEW_CANDIDATE" and deep_decision == "PASS_DEEP_STRONG":
        if multi_verdict in {"PASS_STRONG_WFO", "WATCH_REVIEWABLE"}:
            return "PAPER_REVIEW_READY", reasons
        return "PAPER_REVIEW_READY_WITH_CAUTION", reasons

    if deep_valid > 0 and deep_pos == deep_valid and deep_pf >= 1.25 and deep_ret > 0 and trades >= 150:
        if deep_dd <= 8.0:
            return "WATCH_PAPER_REVIEW_ONLY", reasons
        return "WATCH_PAPER_REVIEW_ONLY_DD_CAUTION", reasons

    return "BLOCK_PAPER_REVIEW", reasons


def fmt_value(value: Any) -> Any:
    return value if value not in ["", [], None] else "none"


def write_md(path: str | Path, plan: dict[str, Any]) -> None:
    lines = [
        "# Tagged MTF Paper Review Plan",
        "",
        "Research/paper-review artifact only. No live orders, no exchange API keys, no automation approval.",
        "",
        f"Status: **{plan['status']}**",
        f"Candidate: **{plan['candidate']}**",
        "",
        "## Evidence",
        f"- Tagged decision: {plan['tagged_decision']}",
        f"- Deep decision: {plan['deep_decision']}",
        f"- Deep folds: {plan['deep_positive_folds']}/{plan['deep_valid_folds']}",
        f"- Deep avg return: {plan['deep_avg_ret_pct']}%",
        f"- Deep avg PF: {plan['deep_avg_pf']}",
        f"- Deep worst DD: {plan['deep_worst_dd_pct']}%",
        f"- Deep trades: {plan['deep_total_trades']}",
        f"- Multi-WFO verdict: {plan['multi_wfo_verdict']}",
        "",
        "## Paper-review guardrails",
        "- Paper only; live trading remains blocked.",
        "- Use the full tagged universe; do not cherry-pick symbols from winners.",
        "- Keep max 1 open position per symbol.",
        "- Stop paper review if daily drawdown exceeds 2%.",
        "- Stop paper review if weekly drawdown exceeds 5%.",
        "- Stop paper review after 3 consecutive stopped-out trades.",
        "- Minimum review sample: 100 closed paper trades or 30 calendar days, whichever comes later.",
        "- Review must compare paper fills with generated signal context before any live discussion.",
        "",
        "## Candidate filters",
    ]
    for key, value in plan.get("candidate_filters", {}).items():
        lines.append(f"- {key}: {fmt_value(value)}")
    lines += ["", "## Reasons"]
    for reason in plan.get("reasons", []):
        lines.append(f"- {reason}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", default="results/tagged_universe_research/tagged_decision/tagged_research_decision.json")
    ap.add_argument("--deep", default="results/tagged_universe_research/deep_validation/deep_validation_summary.json")
    ap.add_argument("--multi", default="results/tagged_universe_research/multi_wfo/tagged_multi_wfo_best.json")
    ap.add_argument("--baseline", default="results/tagged_universe_research/deep_validation/deep_baseline_candidate.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/paper_review")
    args = ap.parse_args()

    decision = load_json(args.decision)
    deep = load_json(args.deep)
    multi = load_json(args.multi)
    baseline = load_json(args.baseline)
    stats = deep_stats(deep)
    status, reasons = verdict(decision, deep, multi)
    candidate = str(baseline.get("name") or deep.get("candidate") or multi.get("name") or "UNKNOWN")

    plan = {
        "status": status,
        "candidate": candidate,
        "tagged_decision": decision.get("decision", ""),
        "deep_decision": deep.get("decision", ""),
        "deep_valid_folds": stats.get("valid_folds", stats.get("folds", 0)),
        "deep_positive_folds": stats.get("positive_folds", 0),
        "deep_avg_ret_pct": stats.get("avg_ret_pct", 0),
        "deep_avg_pf": stats.get("avg_pf", 0),
        "deep_worst_dd_pct": stats.get("worst_max_dd_pct", 0),
        "deep_total_trades": stats.get("total_executed_trades", 0),
        "multi_wfo_verdict": multi.get("wfo_verdict", ""),
        "reasons": reasons,
        "candidate_filters": {
            "min_confidence": baseline.get("min_confidence"),
            "quality_take_threshold": baseline.get("quality_take_threshold"),
            "quality_watch_threshold": baseline.get("quality_watch_threshold"),
            "structure_take_threshold": baseline.get("structure_take_threshold"),
            "structure_watch_threshold": baseline.get("structure_watch_threshold"),
            "min_volume_ratio": baseline.get("min_volume_ratio"),
            "allowed_setup_types": baseline.get("allowed_setup_types", []),
            "blocked_setup_types": baseline.get("blocked_setup_types", []),
            "allowed_trend_contexts": baseline.get("allowed_trend_contexts", []),
            "blocked_trend_contexts": baseline.get("blocked_trend_contexts", []),
            "allowed_direction_contexts": baseline.get("allowed_direction_contexts", []),
            "blocked_direction_contexts": baseline.get("blocked_direction_contexts", []),
            "allowed_volatility_regimes": baseline.get("allowed_volatility_regimes", []),
            "blocked_volatility_regimes": baseline.get("blocked_volatility_regimes", []),
            "allowed_liquidity_states": baseline.get("allowed_liquidity_states", []),
            "blocked_liquidity_states": baseline.get("blocked_liquidity_states", []),
            "allowed_candle_types": baseline.get("allowed_candle_types", []),
            "blocked_candle_types": baseline.get("blocked_candle_types", []),
            "allowed_symbols": baseline.get("allowed_symbols", []),
            "blocked_symbols": baseline.get("blocked_symbols", []),
        },
        "paper_review_rules": {
            "live_trading": "blocked",
            "exchange_api_keys": "not_used",
            "universe": "full_tagged_universe",
            "min_closed_trades": 100,
            "min_calendar_days": 30,
            "daily_drawdown_stop_pct": 2.0,
            "weekly_drawdown_stop_pct": 5.0,
            "max_consecutive_stop_losses": 3,
            "max_symbol_positions": 1,
        },
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "paper_review_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out / "paper_review_plan.md", plan)
    print(out / "paper_review_plan.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
