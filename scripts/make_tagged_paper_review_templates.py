#!/usr/bin/env python3
"""Generate paper-review journal templates from paper_review_plan.json.

Research-only helper. It creates review files, not trades.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def write_header_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=columns).writeheader()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json", default="results/tagged_universe_research/paper_review/paper_review_plan.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/paper_review")
    args = ap.parse_args()

    plan = load_json(args.plan_json)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    trade_cols = [
        "paper_trade_id", "signal_time_utc", "candidate", "symbol", "side", "timeframe",
        "setup_type", "direction_context", "trend_context", "volatility_regime",
        "liquidity_state", "candle_type", "entry_signal", "stop_signal", "take_profit_signal",
        "planned_rr", "paper_status", "paper_entry_time_utc", "paper_entry_price",
        "paper_exit_time_utc", "paper_exit_price", "exit_reason", "result_r", "result_pct",
        "mae_pct", "mfe_pct", "rule_violation", "screenshot_url", "notes",
    ]
    day_cols = [
        "date_utc", "paper_status", "signals_seen", "paper_trades_opened", "paper_trades_closed",
        "closed_wins", "closed_losses", "daily_result_pct", "weekly_result_pct",
        "current_drawdown_pct", "consecutive_stop_losses", "kill_switch_triggered",
        "kill_switch_reason", "notes",
    ]

    write_header_csv(out / "paper_review_journal_template.csv", trade_cols)
    write_header_csv(out / "paper_review_daily_checklist_template.csv", day_cols)

    candidate = plan.get("candidate", "UNKNOWN")
    status = plan.get("status", "UNKNOWN")
    rules = plan.get("paper_review_rules", {})
    filters = plan.get("candidate_filters", {})

    lines = [
        "# Tagged MTF Paper Review Protocol",
        "",
        "This protocol is for paper review only. It does not approve live trading.",
        "",
        f"Candidate: **{candidate}**",
        f"Review status: **{status}**",
        "",
        "## Required sample",
        f"- Closed paper trades: {rules.get('min_closed_trades', 100)} minimum.",
        f"- Calendar days: {rules.get('min_calendar_days', 30)} minimum.",
        "- Use the later condition; do not stop early after a few good trades.",
        "",
        "## Kill-switch rules",
        f"- Daily drawdown stop: {rules.get('daily_drawdown_stop_pct', 2.0)}%.",
        f"- Weekly drawdown stop: {rules.get('weekly_drawdown_stop_pct', 5.0)}%.",
        f"- Consecutive stopped-out trades stop: {rules.get('max_consecutive_stop_losses', 3)}.",
        f"- Max open paper positions per symbol: {rules.get('max_symbol_positions', 1)}.",
        "",
        "## Candidate filter snapshot",
    ]
    for key in sorted(filters):
        value: Any = filters.get(key)
        if value in (None, "", []):
            value = "none"
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "## Record every signal",
        "- Record context, setup, signal prices, paper fill, exit and result.",
        "- Mark every rule violation instead of silently deleting bad trades.",
        "- Keep screenshots or chart notes for questionable entries.",
        "",
        "## Files",
        "- paper_review_journal_template.csv",
        "- paper_review_daily_checklist_template.csv",
    ]
    (out / "paper_review_protocol.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(out / "paper_review_protocol.md")
    print(out / "paper_review_journal_template.csv")
    print(out / "paper_review_daily_checklist_template.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
