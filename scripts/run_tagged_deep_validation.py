#!/usr/bin/env python3
"""Run deeper validation for the current tagged multi-WFO best candidate.

This step does not create a new strategy variant. It takes the best candidate
from tagged_multi_wfo_best.json, rebuilds its exact matrix baseline, and runs a
larger walk-forward validation on the same tagged universe.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from promote_matrix_baseline import normalize_row  # noqa: E402


def read_csv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


def pct(part: int, total: int) -> float:
    return round(part / total * 100.0, 2) if total else 0.0


def run_cmd(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def find_matrix_row(matrix_path: str | Path, candidate_name: str) -> dict[str, str]:
    rows = read_csv(matrix_path)
    for row in rows:
        if str(row.get("name", "")).strip() == candidate_name:
            return row
    raise SystemExit(f"Candidate not found in matrix summary: {candidate_name}")


def aggregate_wfo(rows: list[dict[str, str]]) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "OK"]
    positive = [r for r in ok if to_float(r.get("ret_pct")) > 0]
    non_fail = [r for r in ok if r.get("sanity_status") in {"OK", "WARN"}]
    avg_ret = round(mean([to_float(r.get("ret_pct")) for r in ok]), 4) if ok else 0.0
    avg_pf = round(mean([to_float(r.get("pf")) for r in ok]), 4) if ok else 0.0
    worst_dd = round(max([abs(to_float(r.get("max_dd_pct"))) for r in ok], default=0.0), 4)
    executed = sum(to_int(r.get("executed_trades")) for r in ok)
    return {
        "folds": len(rows),
        "valid_folds": len(ok),
        "positive_folds": len(positive),
        "positive_fold_pct": pct(len(positive), len(ok)),
        "sanity_non_fail_folds": len(non_fail),
        "sanity_non_fail_pct": pct(len(non_fail), len(ok)),
        "total_executed_trades": executed,
        "avg_ret_pct": avg_ret,
        "avg_pf": avg_pf,
        "worst_max_dd_pct": worst_dd,
    }


def verdict(agg: dict[str, Any]) -> str:
    valid = to_int(agg.get("valid_folds"))
    positive = to_int(agg.get("positive_folds"))
    executed = to_int(agg.get("total_executed_trades"))
    positive_pct = to_float(agg.get("positive_fold_pct"))
    non_fail_pct = to_float(agg.get("sanity_non_fail_pct"))
    avg_pf = to_float(agg.get("avg_pf"))
    avg_ret = to_float(agg.get("avg_ret_pct"))
    worst_dd = to_float(agg.get("worst_max_dd_pct"))

    if valid == 0:
        return "BLOCK_NO_VALID_FOLDS"
    if executed < 100:
        return "WATCH_TOO_SPARSE"
    if positive == valid and avg_pf >= 1.40 and avg_ret > 0 and worst_dd <= 7.0 and non_fail_pct == 100.0:
        return "PASS_DEEP_STRONG"
    if positive_pct >= 75.0 and avg_pf >= 1.30 and avg_ret > 0 and worst_dd <= 8.0 and non_fail_pct == 100.0:
        return "PASS_DEEP_REVIEWABLE"
    if positive_pct >= 66.0 and avg_pf >= 1.15 and avg_ret > 0 and worst_dd <= 10.0:
        return "WATCH_DEEP_UNSTABLE"
    return "BLOCK_DEEP_WEAK"


def build_md(candidate_name: str, baseline: dict[str, Any], multi_best: dict[str, Any], agg: dict[str, Any], fold_rows: list[dict[str, str]], decision: str, args: argparse.Namespace) -> str:
    lines = [
        "# Tagged Deep Validation",
        "",
        "This validates the current tagged multi-WFO best candidate on a larger walk-forward sample.",
        "Universe/tags are unchanged. No live/paper deployment is approved here.",
        "",
        "## Candidate",
        f"- Name: **{candidate_name}**",
        f"- Source multi-WFO verdict: {multi_best.get('wfo_verdict', '')}",
        f"- Source multi-WFO folds: {multi_best.get('positive_folds', '')}/{multi_best.get('valid_folds', '')}",
        f"- Source multi-WFO avg PF: {multi_best.get('wfo_avg_pf', '')}",
        f"- Source multi-WFO avg return: {multi_best.get('wfo_avg_ret_pct', '')}%",
        "",
        "## Deep validation settings",
        f"- interval: {args.interval}",
        f"- limit: {args.limit}",
        f"- windows: {args.windows}",
        f"- lookback_days: {args.lookback_days}",
        f"- profile: {args.profile}",
        "",
        "## Deep validation aggregate",
        f"- Decision: **{decision}**",
    ]
    for key, value in agg.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Baseline filters"])
    for key in [
        "min_confidence", "quality_take_threshold", "quality_watch_threshold",
        "structure_take_threshold", "structure_watch_threshold", "min_volume_ratio",
        "allowed_setup_types", "blocked_setup_types", "blocked_volatility_regimes",
        "blocked_trend_contexts", "blocked_direction_contexts", "blocked_liquidity_states", "blocked_candle_types",
        "allowed_symbols",
    ]:
        value = baseline.get(key, "")
        if isinstance(value, list):
            value = ", ".join(str(x) for x in value) or "none"
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Folds"])
    for row in fold_rows:
        lines.append(
            f"- {row.get('fold')}: status={row.get('status')}, ret={row.get('ret_pct')}%, "
            f"pf={row.get('pf')}, dd={row.get('max_dd_pct')}%, executed={row.get('executed_trades')}, "
            f"sanity={row.get('sanity_status')}"
        )
    lines.extend(["", "## Next step"])
    if decision in {"PASS_DEEP_STRONG", "PASS_DEEP_REVIEWABLE"}:
        lines.append("- Candidate passed deeper validation. Next step is paper-review logic and risk review, not live mode.")
    elif decision == "WATCH_DEEP_UNSTABLE":
        lines.append("- Candidate is still promising but unstable. Inspect weak folds before paper review.")
    else:
        lines.append("- Candidate did not pass deeper validation. Continue strategy diagnostics before promotion.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run deeper validation for tagged multi-WFO best candidate.")
    ap.add_argument("--matrix", default="results/tagged_universe_research/matrix/matrix_summary.csv")
    ap.add_argument("--multi-best", default="results/tagged_universe_research/multi_wfo/tagged_multi_wfo_best.json")
    ap.add_argument("--symbols-file", default="results/strategy_universe_layer/combined_symbols.txt")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/deep_validation")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--limit", type=int, default=2500)
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--lookback-days", type=int, default=60)
    ap.add_argument("--profile", default="growth_100_20x")
    ap.add_argument("--sleep-sec", type=float, default=0.05)
    args = ap.parse_args()

    multi_best = read_json(args.multi_best)
    candidate_name = str(multi_best.get("name", "")).strip()
    if not candidate_name:
        raise SystemExit(f"No candidate name in multi-best json: {args.multi_best}")

    matrix_row = find_matrix_row(args.matrix, candidate_name)
    baseline = normalize_row(matrix_row)
    baseline["source_matrix"] = str(args.matrix)
    baseline["source_multi_wfo_best"] = str(args.multi_best)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    baseline_path = out / "deep_baseline_candidate.json"
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run_cmd([
        sys.executable,
        "scripts/run_binance_walk_forward_v2.py",
        "--symbols-file", args.symbols_file,
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--candles-out", str(out / "deep_walk_forward_candles.csv"),
        "--out-dir", str(out),
        "--baseline", str(baseline_path),
        "--profile", args.profile,
        "--windows", str(args.windows),
        "--lookback-days", str(args.lookback_days),
        "--sleep-sec", str(args.sleep_sec),
    ])

    fold_rows = read_csv(out / "walk_forward_summary.csv")
    agg = aggregate_wfo(fold_rows)
    decision = verdict(agg)
    summary = {
        "candidate": candidate_name,
        "decision": decision,
        "settings": {
            "interval": args.interval,
            "limit": args.limit,
            "windows": args.windows,
            "lookback_days": args.lookback_days,
            "profile": args.profile,
        },
        "multi_wfo_best": multi_best,
        "deep_validation": agg,
        "baseline": baseline,
    }
    (out / "deep_validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "deep_validation_summary.md").write_text(build_md(candidate_name, baseline, multi_best, agg, fold_rows, decision, args), encoding="utf-8")
    print(out / "deep_validation_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
