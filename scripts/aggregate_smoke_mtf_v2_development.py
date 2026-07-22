#!/usr/bin/env python3
"""Aggregate 100 frozen SMOKE MTF V2 development side-partition artifacts."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from strategy_lab.market_data import parse_dt
from strategy_lab.mtf_development_backtest_v1 import TradeCandidate, accepted_to_dict, simulate_portfolio


def candidate_from_dict(row: dict) -> TradeCandidate:
    return TradeCandidate(
        symbol=str(row["symbol"]).upper(), side=str(row["side"]), fold=int(row["fold"]),
        entry_time=parse_dt(row["entry_time"]), entry=float(row["entry"]), stop=float(row["stop"]),
        target=float(row["target"]), exit_time=parse_dt(row["exit_time"]), exit_price=float(row["exit_price"]),
        exit_reason=str(row["exit_reason"]), gross_return_fraction=float(row["gross_return_fraction"]),
        funding_return_fraction=float(row["funding_return_fraction"]), net_return_fraction=float(row["net_return_fraction"]),
        structural_risk_fraction=float(row["structural_risk_fraction"]),
        event_risk_multiplier=float(row["event_risk_multiplier"]), planned_rr=float(row["planned_rr"]),
        quality_score=float(row["quality_score"]), target_timeframe=str(row.get("target_timeframe") or ""),
        target_source=str(row.get("target_source") or ""),
    )


def expected_partition_keys() -> set[tuple[str, int, str]]:
    return {
        (symbol, fold, side)
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
        for fold in range(10)
        for side in ("long", "short")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--expected-parts", type=int, default=100)
    args = parser.parse_args()

    root = Path(args.parts_root)
    files = sorted(root.rglob("fold_candidates.json"))
    if len(files) != args.expected_parts:
        raise RuntimeError(f"expected {args.expected_parts} fold parts, found {len(files)}")
    seen: set[tuple[str, int, str]] = set()
    candidates: list[TradeCandidate] = []
    part_summaries: list[dict] = []
    funding_complete = True
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("recognition_freeze_sha") != "492eee9fdba5993b7f518e9a1ff38576e8b14285":
            raise RuntimeError(f"unexpected recognition freeze in {path}")
        summary = payload["summary"]
        key = (str(summary["symbol"]).upper(), int(summary["fold"]), str(summary["side"]))
        if key in seen:
            raise RuntimeError(f"duplicate symbol/fold/side part: {key}")
        seen.add(key)
        part_summaries.append(summary)
        funding_status = str(payload.get("funding_coverage_status") or "UNKNOWN")
        funding_complete = funding_complete and funding_status == "OK"
        candidates.extend(candidate_from_dict(row) for row in payload.get("candidates", []))
    expected = expected_partition_keys()
    if seen != expected:
        raise RuntimeError(f"fold partition mismatch missing={sorted(expected-seen)} extra={sorted(seen-expected)}")

    accepted, portfolio = simulate_portfolio(candidates)
    pf_value = float("inf") if portfolio["pooled_profit_factor_infinite"] else float(portfolio["pooled_profit_factor"] or 0.0)
    gates = {
        "minimum_trades_60": int(portfolio["accepted_trades"]) >= 60,
        "pooled_profit_factor_at_least_1_20": pf_value >= 1.20,
        "positive_average_trade_return": float(portfolio["average_trade_return_after_costs"]) > 0.0,
        "positive_folds_at_least_6_of_10": int(portfolio["positive_folds"]) >= 6,
        "portfolio_max_drawdown_at_most_8_pct": float(portfolio["portfolio_max_drawdown_pct"]) <= 8.0,
    }
    verdict = "INCOMPLETE_FUNDING_DATA" if not funding_complete else ("PASS" if all(gates.values()) else "FAIL")
    result = {
        "study_id": "SMOKE_MTF_V2_DEVELOPMENT_PROFITABILITY_V2",
        "status": "COMPLETED", "verdict": verdict,
        "recognition_freeze_sha": "492eee9fdba5993b7f518e9a1ff38576e8b14285",
        "candidate_count": 1, "candidate": "SMOKE_MTF_DEALING_RANGE_V2_FROZEN_CORE_V2",
        "partitioning": "100 execution-only symbol/fold/side parts; exact union of the frozen long and short candidate stream",
        "event_layer": {"included": False, "reason": "No causal point-in-time historical event snapshot exists; event risk is not credited in development performance.", "prospective_overlay_only": True},
        "funding_complete": funding_complete, "candidate_signals": len(candidates),
        "portfolio": portfolio, "gates": gates, "all_gates_pass": all(gates.values()),
        "parts": sorted(part_summaries, key=lambda item: (item["fold"], item["symbol"], item["side"])),
        "prohibitions": {"external_holdout": verdict != "PASS", "paper": verdict != "PASS", "vps": verdict != "PASS", "live": True, "tuning_after_result": True},
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "development_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trade_rows = [accepted_to_dict(row) for row in accepted]
    fields = list(trade_rows[0].keys()) if trade_rows else ["symbol","side","fold","entry_time","entry","stop","target","exit_time","exit_price","exit_reason","net_return_fraction","risk_cash","notional","pnl_cash","equity_after_exit"]
    with (out / "accepted_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(trade_rows)
    lines = [
        "# SMOKE MTF V2 — Development Profitability V2", "",
        f"- Verdict: **{verdict}**", f"- Candidate signals: **{len(candidates)}**",
        f"- Accepted trades: **{portfolio['accepted_trades']}**",
        f"- Pooled PF: **{'∞' if portfolio['pooled_profit_factor_infinite'] else portfolio['pooled_profit_factor']}**",
        f"- Average trade return after costs: **{portfolio['average_trade_return_after_costs']}**",
        f"- Positive folds: **{portfolio['positive_folds']}/10**",
        f"- Portfolio max drawdown: **{portfolio['portfolio_max_drawdown_pct']}%**",
        f"- Net return: **{portfolio['net_return_pct']}%**",
        f"- Funding coverage: **{'PASS' if funding_complete else 'INCOMPLETE'}**",
        "- Event layer: **not credited; prospective overlay only**", "", "## Gates",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} — `{name}`" for name, passed in gates.items())
    (out / "DEVELOPMENT_RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "portfolio": portfolio, "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
