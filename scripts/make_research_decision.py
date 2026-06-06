#!/usr/bin/env python3
"""Build a final research decision from matrix, baseline, and walk-forward outputs.

This gate does not approve live trading. It produces a compact, reviewable
research decision so the next action is explicit: expand test, tune strategy,
or promote to deeper paper-mode review.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def read_first_csv(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    with p.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def read_csv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except (TypeError, ValueError):
        return default


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value not in {None, ""} else default))
    except (TypeError, ValueError):
        return default


def pct(part: int, total: int) -> float:
    return round(part / total * 100.0, 2) if total else 0.0


def aggregate_walk_forward(rows: list[dict[str, str]]) -> dict[str, object]:
    ok_rows = [r for r in rows if r.get("status") == "OK"]
    positive_rows = [r for r in ok_rows if to_float(r.get("ret_pct")) > 0]
    sanity_ok_rows = [r for r in ok_rows if r.get("sanity_status") == "OK"]
    sanity_non_fail_rows = [r for r in ok_rows if r.get("sanity_status") in {"OK", "WARN"}]
    total_executed = sum(to_int(r.get("executed_trades")) for r in ok_rows)
    avg_ret = round(mean([to_float(r.get("ret_pct")) for r in ok_rows]), 4) if ok_rows else 0.0
    avg_pf = round(mean([to_float(r.get("pf")) for r in ok_rows]), 4) if ok_rows else 0.0
    worst_dd = round(max([abs(to_float(r.get("max_dd_pct"))) for r in ok_rows], default=0.0), 4)
    return {
        "folds": len(rows),
        "valid_folds": len(ok_rows),
        "positive_folds": len(positive_rows),
        "positive_fold_pct": pct(len(positive_rows), len(ok_rows)),
        "sanity_ok_folds": len(sanity_ok_rows),
        "sanity_ok_pct": pct(len(sanity_ok_rows), len(ok_rows)),
        "sanity_non_fail_folds": len(sanity_non_fail_rows),
        "sanity_non_fail_pct": pct(len(sanity_non_fail_rows), len(ok_rows)),
        "total_executed_trades": total_executed,
        "avg_ret_pct": avg_ret,
        "avg_pf": avg_pf,
        "worst_max_dd_pct": worst_dd,
    }


def decide(matrix_best: dict[str, str], baseline: dict, wfo: dict[str, object]) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    next_steps: list[str] = []

    matrix_executed = to_int(matrix_best.get("executed_trades"))
    matrix_sanity = matrix_best.get("sanity_status", "UNKNOWN")
    baseline_name = baseline.get("name") or matrix_best.get("name") or "UNKNOWN"
    valid_folds = to_int(wfo.get("valid_folds"))
    total_folds = to_int(wfo.get("folds"))
    wfo_executed = to_int(wfo.get("total_executed_trades"))
    positive_pct = to_float(wfo.get("positive_fold_pct"))
    sanity_ok_pct = to_float(wfo.get("sanity_ok_pct"))
    sanity_non_fail_pct = to_float(wfo.get("sanity_non_fail_pct"))
    avg_pf = to_float(wfo.get("avg_pf"))
    avg_ret = to_float(wfo.get("avg_ret_pct"))
    worst_dd = to_float(wfo.get("worst_max_dd_pct"))

    if not matrix_best:
        return "BLOCK_NO_MATRIX", ["matrix_summary.csv is missing or empty"], ["Run the matrix step before making a research decision."]
    if not baseline:
        reasons.append("baseline_candidate.json is missing; decision uses matrix row only")
    if valid_folds == 0:
        return "BLOCK_NO_VALID_WFO", ["walk-forward produced no valid folds"], ["Fix walk-forward windows/data before continuing."]

    reasons.append(f"baseline={baseline_name}")
    reasons.append(f"matrix_sanity={matrix_sanity}")
    reasons.append(f"matrix_executed={matrix_executed}")
    reasons.append(f"wfo_valid_folds={valid_folds}/{total_folds}")
    reasons.append(f"wfo_executed={wfo_executed}")
    reasons.append(f"wfo_positive_fold_pct={positive_pct}")
    reasons.append(f"wfo_sanity_ok_pct={sanity_ok_pct}")
    reasons.append(f"wfo_sanity_non_fail_pct={sanity_non_fail_pct}")
    reasons.append(f"wfo_avg_pf={avg_pf}")
    reasons.append(f"wfo_avg_ret_pct={avg_ret}")
    reasons.append(f"wfo_worst_dd_pct={worst_dd}")

    if matrix_sanity == "FAIL":
        next_steps.append("Fix report sanity failures in the matrix baseline before further validation.")
        return "BLOCK_SANITY_FAIL", reasons, next_steps

    if matrix_executed < 10 or wfo_executed < 10:
        next_steps.append("Run a larger test: more symbols and/or a longer candle limit before promoting the baseline.")
        next_steps.append("Keep this candidate, but treat current results as too sparse for strategy decisions.")
        return "WATCH_EXPAND_SAMPLE", reasons, next_steps

    if positive_pct < 50 or avg_pf < 1.0 or avg_ret <= 0:
        next_steps.append("Compare fold diagnostics and identify weak setup_type/trend_context/volatility_regime groups.")
        next_steps.append("Do not promote this baseline yet; tune entries/exits or filters first.")
        return "WATCH_TUNE_STRATEGY", reasons, next_steps

    if worst_dd > 15:
        next_steps.append("Drawdown is high. Reduce risk profile or tighten filters before paper-mode review.")
        return "WATCH_RISK_REVIEW", reasons, next_steps

    strong_wfo = positive_pct >= 75 and sanity_non_fail_pct >= 100 and avg_pf >= 1.20 and avg_ret > 0 and worst_dd <= 10
    very_strong_wfo = positive_pct >= 100 and sanity_non_fail_pct >= 100 and avg_pf >= 1.50 and avg_ret > 0 and worst_dd <= 8

    if matrix_sanity in {"OK", "WARN"} and strong_wfo:
        if matrix_sanity == "OK" and very_strong_wfo:
            next_steps.append("Promote candidate to deeper research. Matrix sanity is OK and walk-forward is strong despite review warnings in some folds.")
            next_steps.append("Do not use live trading yet; require larger history and paper-decision confirmation before deployment discussion.")
            return "PROMOTE_TO_DEEPER_RESEARCH", reasons, next_steps
        next_steps.append("Promote candidate to deeper paper-mode review. WARN-only fold sanity is acceptable at this stage, but inspect time-stop diagnostics first.")
        next_steps.append("Do not use live trading yet; require paper-mode review and larger history before any deployment discussion.")
        return "PROMOTE_TO_PAPER_REVIEW", reasons, next_steps

    if sanity_ok_pct < 70:
        next_steps.append("Investigate sanity warnings/errors across folds before paper-mode review.")
        return "WATCH_SANITY_REVIEW", reasons, next_steps

    next_steps.append("Promote candidate to deeper paper-mode review on a larger universe/history.")
    next_steps.append("Do not use live trading yet; require larger sample and paper decision first.")
    return "PROMOTE_TO_DEEPER_RESEARCH", reasons, next_steps


def build_markdown(decision: dict[str, object]) -> str:
    lines = [
        "# Smoke Strategy Research Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        "## Baseline",
    ]
    baseline = decision.get("baseline", {}) or {}
    for key in [
        "name",
        "rolling_top_n",
        "require_rolling_top",
        "require_universe_gate",
        "min_confidence",
        "quality_take_threshold",
        "quality_watch_threshold",
        "structure_take_threshold",
        "structure_watch_threshold",
        "min_volume_ratio",
    ]:
        lines.append(f"- {key}: {baseline.get(key, '')}")

    lines.extend(["", "## Matrix best row"])
    matrix = decision.get("matrix_best", {}) or {}
    for key in ["name", "score", "ret_pct", "max_dd_pct", "pf", "winrate", "executed_trades", "sanity_status", "diagnosis_flags"]:
        lines.append(f"- {key}: {matrix.get(key, '')}")

    lines.extend(["", "## Walk-forward aggregate"])
    wfo = decision.get("walk_forward", {}) or {}
    for key, value in wfo.items():
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
    parser = argparse.ArgumentParser(description="Make final research decision from matrix and walk-forward outputs.")
    parser.add_argument("--matrix", default="results/binance_real_matrix/matrix_summary.csv")
    parser.add_argument("--baseline", default="results/binance_real_matrix/baseline_candidate/baseline_candidate.json")
    parser.add_argument("--walk-forward", default="results/binance_walk_forward/walk_forward_summary.csv")
    parser.add_argument("--out-dir", default="results/research_decision")
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless decision is a promotion decision")
    args = parser.parse_args()

    matrix_best = read_first_csv(args.matrix)
    baseline = read_json(args.baseline)
    wfo_rows = read_csv(args.walk_forward)
    wfo = aggregate_walk_forward(wfo_rows)
    decision_value, reasons, next_steps = decide(matrix_best, baseline, wfo)

    decision = {
        "decision": decision_value,
        "matrix_best": matrix_best,
        "baseline": baseline,
        "walk_forward": wfo,
        "reasons": reasons,
        "next_steps": next_steps,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "research_decision.md").write_text(build_markdown(decision), encoding="utf-8")

    print(build_markdown(decision))
    if args.strict and decision_value not in {"PROMOTE_TO_DEEPER_RESEARCH", "PROMOTE_TO_PAPER_REVIEW"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
