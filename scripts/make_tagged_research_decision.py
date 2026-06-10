#!/usr/bin/env python3
"""Make tagged-universe research decision from multi-WFO and deep validation.

This supersedes the old matrix-only decision for tagged research. The selected
candidate must come from tagged_multi_wfo_best.json, and deep validation is used
as the stronger final gate.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def decide(multi: dict[str, Any], deep_summary: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    next_steps: list[str] = []
    candidate = multi.get("name") or deep_summary.get("candidate") or "UNKNOWN"
    deep = deep_summary.get("deep_validation", {}) or {}
    deep_decision = deep_summary.get("decision", "UNKNOWN")

    multi_folds = f"{multi.get('positive_folds', '')}/{multi.get('valid_folds', '')}"
    multi_pf = to_float(multi.get("wfo_avg_pf"))
    multi_ret = to_float(multi.get("wfo_avg_ret_pct"))
    multi_dd = to_float(multi.get("wfo_worst_dd_pct"))
    deep_valid = to_int(deep.get("valid_folds"))
    deep_positive = to_int(deep.get("positive_folds"))
    deep_pf = to_float(deep.get("avg_pf"))
    deep_ret = to_float(deep.get("avg_ret_pct"))
    deep_dd = to_float(deep.get("worst_max_dd_pct"))
    deep_trades = to_int(deep.get("total_executed_trades"))

    reasons.extend([
        f"candidate={candidate}",
        f"multi_wfo_verdict={multi.get('wfo_verdict', '')}",
        f"multi_wfo_folds={multi_folds}",
        f"multi_wfo_avg_pf={multi_pf}",
        f"multi_wfo_avg_ret_pct={multi_ret}",
        f"multi_wfo_worst_dd_pct={multi_dd}",
        f"deep_decision={deep_decision}",
        f"deep_valid_folds={deep_valid}",
        f"deep_positive_folds={deep_positive}",
        f"deep_avg_pf={deep_pf}",
        f"deep_avg_ret_pct={deep_ret}",
        f"deep_worst_dd_pct={deep_dd}",
        f"deep_total_trades={deep_trades}",
    ])

    if not multi:
        return "BLOCK_NO_MULTI_WFO", ["tagged_multi_wfo_best.json is missing"], ["Run tagged multi-WFO before making a tagged decision."]
    if not deep_summary:
        return "BLOCK_NO_DEEP_VALIDATION", reasons + ["deep_validation_summary.json is missing"], ["Run tagged deep validation before promotion discussion."]
    if deep_decision in {"PASS_DEEP_STRONG", "PASS_DEEP_REVIEWABLE"}:
        next_steps.append("Candidate passed tagged deep validation. Move to paper-review design and risk diagnostics, not live mode.")
        next_steps.append("Keep universe/tags unchanged; continue monitoring weak folds and stop-loss pressure.")
        return "PROMOTE_TO_PAPER_REVIEW_CANDIDATE", reasons, next_steps
    if deep_decision == "WATCH_DEEP_UNSTABLE":
        next_steps.append("Candidate remains promising but unstable on deeper validation. Inspect weak folds before paper review.")
        next_steps.append("Do not create new coin/sector filters; diagnose setup/context and risk first.")
        return "WATCH_DEEP_VALIDATION", reasons, next_steps

    next_steps.append("Candidate did not pass deeper validation. Continue strategy diagnostics before any paper-review discussion.")
    return "BLOCK_DEEP_VALIDATION", reasons, next_steps


def build_md(decision: dict[str, Any]) -> str:
    lines = [
        "# Tagged Research Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        "## Candidate",
    ]
    multi = decision.get("multi_wfo_best", {}) or {}
    deep = decision.get("deep_validation", {}) or {}
    lines.append(f"- Name: {multi.get('name') or deep.get('candidate') or ''}")
    lines.append(f"- Multi-WFO verdict: {multi.get('wfo_verdict', '')}")
    lines.append(f"- Multi-WFO folds: {multi.get('positive_folds', '')}/{multi.get('valid_folds', '')}")
    lines.append(f"- Multi-WFO avg PF: {multi.get('wfo_avg_pf', '')}")
    lines.append(f"- Multi-WFO avg return: {multi.get('wfo_avg_ret_pct', '')}%")
    lines.append(f"- Multi-WFO worst DD: {multi.get('wfo_worst_dd_pct', '')}%")
    lines.extend(["", "## Deep validation"])
    lines.append(f"- Deep decision: {deep.get('decision', '')}")
    agg = deep.get("deep_validation", {}) or {}
    for key, value in agg.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Reasons"])
    for reason in decision.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "## Next steps"])
    for step in decision.get("next_steps", []):
        lines.append(f"- {step}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Make tagged research decision from multi-WFO and deep validation.")
    ap.add_argument("--multi-best", default="results/tagged_universe_research/multi_wfo/tagged_multi_wfo_best.json")
    ap.add_argument("--deep-summary", default="results/tagged_universe_research/deep_validation/deep_validation_summary.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/tagged_decision")
    args = ap.parse_args()

    multi = read_json(args.multi_best)
    deep = read_json(args.deep_summary)
    decision_value, reasons, next_steps = decide(multi, deep)
    decision = {
        "decision": decision_value,
        "multi_wfo_best": multi,
        "deep_validation": deep,
        "reasons": reasons,
        "next_steps": next_steps,
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tagged_research_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "tagged_research_decision.md").write_text(build_md(decision), encoding="utf-8")
    print(build_md(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
