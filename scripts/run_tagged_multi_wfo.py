#!/usr/bin/env python3
"""Run walk-forward comparison for multiple tagged-universe candidates.

Why this exists:
- matrix winner can be overfiltered and look beautiful on one split;
- tagged universe must not be judged by a single candidate;
- we need WFO comparison across several strategy-logic variants before any
  baseline promotion discussion.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from promote_matrix_baseline import normalize_row  # noqa: E402

DEFAULT_CANDIDATES = (
    "TAGGED_LOGIC_TREND_LIQ_NO_RANGE_ROTATION_V5,"
    "TAGGED_LOGIC_TREND_LIQ_NO_RANGE_NO_IGNITION_V5,"
    "TAGGED_LOGIC_TREND_LIQ_DISCOVERY_STRICT_V5,"
    "TAGGED_LOGIC_TREND_LIQUIDITY_BALANCED_V2,"
    "TAGGED_LOGIC_TREND_LIQ_NO_IGNITION_V4"
)


def read_csv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


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


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "candidate"


def parse_names(value: str) -> list[str]:
    return [part.strip() for part in str(value).split(",") if part.strip()]


def run_cmd(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def select_rows(matrix_rows: list[dict[str, str]], candidate_names: list[str]) -> list[dict[str, str]]:
    by_name = {str(row.get("name", "")).strip(): row for row in matrix_rows if str(row.get("name", "")).strip()}
    rows: list[dict[str, str]] = []
    missing: list[str] = []
    for name in candidate_names:
        row = by_name.get(name)
        if row is None:
            missing.append(name)
            continue
        rows.append(row)
    if missing:
        print("Missing requested candidates: " + ", ".join(missing))
    if rows:
        return rows

    fallback = []
    for row in matrix_rows:
        name = str(row.get("name", ""))
        if not name.startswith("TAGGED_"):
            continue
        if str(row.get("allowed_symbols_filter", "")).strip():
            continue
        if to_int(row.get("executed_trades")) < 30:
            continue
        if str(row.get("sanity_status", "")) not in {"OK", "WARN"}:
            continue
        fallback.append(row)
    return sorted(
        fallback,
        key=lambda r: (
            to_float(r.get("ret_pct")),
            to_float(r.get("pf")),
            -abs(to_float(r.get("max_dd_pct"))),
            to_int(r.get("executed_trades")),
        ),
        reverse=True,
    )[:5]


def summarize_wfo(path: str | Path) -> dict[str, Any]:
    rows = read_csv(path)
    ok = [r for r in rows if r.get("status") == "OK"]
    positive = [r for r in ok if to_float(r.get("ret_pct")) > 0]
    non_fail = [r for r in ok if r.get("sanity_status") in {"OK", "WARN"}]
    avg_ret = round(mean([to_float(r.get("ret_pct")) for r in ok]), 4) if ok else 0.0
    avg_pf = round(mean([to_float(r.get("pf")) for r in ok]), 4) if ok else 0.0
    worst_dd = round(max([abs(to_float(r.get("max_dd_pct"))) for r in ok], default=0.0), 4)
    executed = sum(to_int(r.get("executed_trades")) for r in ok)
    positive_pct = round(len(positive) / len(ok) * 100.0, 2) if ok else 0.0
    non_fail_pct = round(len(non_fail) / len(ok) * 100.0, 2) if ok else 0.0

    if not ok:
        verdict = "BLOCK_NO_VALID_FOLDS"
    elif executed < 30:
        verdict = "WATCH_TOO_SPARSE"
    elif len(positive) == len(ok) and avg_pf >= 1.35 and avg_ret > 0 and worst_dd <= 8.0 and non_fail_pct == 100.0:
        verdict = "PASS_STRONG_WFO"
    elif positive_pct >= 75.0 and avg_pf >= 1.20 and avg_ret > 0 and worst_dd <= 10.0 and non_fail_pct == 100.0:
        verdict = "WATCH_REVIEWABLE"
    elif positive_pct >= 50.0 and avg_ret > 0 and avg_pf >= 1.0:
        verdict = "WATCH_UNSTABLE"
    else:
        verdict = "BLOCK_WEAK_WFO"

    return {
        "valid_folds": len(ok),
        "total_folds": len(rows),
        "positive_folds": len(positive),
        "positive_fold_pct": positive_pct,
        "sanity_non_fail_pct": non_fail_pct,
        "wfo_total_trades": executed,
        "wfo_avg_ret_pct": avg_ret,
        "wfo_avg_pf": avg_pf,
        "wfo_worst_dd_pct": worst_dd,
        "wfo_verdict": verdict,
    }


def score_candidate(row: dict[str, Any]) -> float:
    verdict_rank = {
        "PASS_STRONG_WFO": 100.0,
        "WATCH_REVIEWABLE": 70.0,
        "WATCH_UNSTABLE": 35.0,
        "WATCH_TOO_SPARSE": 10.0,
        "BLOCK_WEAK_WFO": -20.0,
        "BLOCK_NO_VALID_FOLDS": -50.0,
    }.get(str(row.get("wfo_verdict")), 0.0)
    sample_bonus = min(to_int(row.get("wfo_total_trades")), 300) / 30.0
    return round(
        verdict_rank
        + to_float(row.get("wfo_avg_ret_pct")) * 4.0
        + min(to_float(row.get("wfo_avg_pf")), 3.0) * 3.0
        + to_float(row.get("positive_fold_pct")) * 0.15
        - to_float(row.get("wfo_worst_dd_pct")) * 0.75
        + sample_bonus,
        4,
    )


def write_md(path: str | Path, rows: list[dict[str, Any]]) -> None:
    ranked = sorted(rows, key=lambda r: to_float(r.get("multi_wfo_score")), reverse=True)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tagged Multi-WFO Comparison",
        "",
        "This compares multiple tagged-universe strategy candidates on walk-forward validation.",
        "Universe/tags are unchanged. Sector tags are context only. No live/paper promotion is performed here.",
        "",
        "## Ranked candidates",
        "",
    ]
    for row in ranked:
        lines.append(
            f"- **{row['name']}**: multi_score={row['multi_wfo_score']}, verdict={row['wfo_verdict']}, "
            f"folds={row['positive_folds']}/{row['valid_folds']}, avg_ret={row['wfo_avg_ret_pct']}%, "
            f"avg_pf={row['wfo_avg_pf']}, worst_dd={row['wfo_worst_dd_pct']}%, "
            f"wfo_trades={row['wfo_total_trades']}, matrix_ret={row['matrix_ret_pct']}%, "
            f"matrix_pf={row['matrix_pf']}, matrix_dd={row['matrix_dd_pct']}%, matrix_trades={row['matrix_executed_trades']}, "
            f"matrix_flags={row['matrix_diagnosis_flags'] or 'none'}"
        )
    lines += ["", "## Decision rule", ""]
    lines.append("- Do not choose a candidate only because matrix PF is high.")
    lines.append("- Prefer candidates with 3/4 or 4/4 positive folds, positive avg return, controlled DD, and enough trades.")
    lines.append("- Overfiltered candidates stay as diagnostics unless WFO also passes.")
    lines.append("")
    if ranked:
        best = ranked[0]
        lines += ["## Current best by multi-WFO", ""]
        lines.append(f"- Candidate: **{best['name']}**")
        lines.append(f"- Verdict: **{best['wfo_verdict']}**")
        if best["wfo_verdict"] in {"PASS_STRONG_WFO", "WATCH_REVIEWABLE"}:
            lines.append("- Next: review selection report and consider deeper validation, not live mode.")
        else:
            lines.append("- Next: tune strategy logic again; do not promote this candidate.")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run multi-WFO comparison for tagged-universe candidates.")
    ap.add_argument("--matrix", default="results/tagged_universe_research/matrix/matrix_summary.csv")
    ap.add_argument("--symbols-file", default="results/strategy_universe_layer/combined_symbols.txt")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/multi_wfo")
    ap.add_argument("--candidate-names", default=DEFAULT_CANDIDATES)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--lookback-days", type=int, default=30)
    ap.add_argument("--profile", default="growth_100_20x")
    ap.add_argument("--sleep-sec", type=float, default=0.05)
    args = ap.parse_args()

    matrix_rows = read_csv(args.matrix)
    if not matrix_rows:
        raise SystemExit(f"No matrix rows found: {args.matrix}")
    candidates = select_rows(matrix_rows, parse_names(args.candidate_names))
    if not candidates:
        raise SystemExit("No candidates selected for multi-WFO")

    out = Path(args.out_dir)
    baselines_dir = out / "baselines"
    baselines_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    for row in candidates:
        name = str(row.get("name", "")).strip()
        slug = safe_name(name)
        baseline = normalize_row(row)
        baseline["source_matrix"] = str(args.matrix)
        baseline_path = baselines_dir / f"{slug}.json"
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        candidate_out = out / slug
        run_cmd([
            sys.executable,
            "scripts/run_binance_walk_forward_v2.py",
            "--symbols-file", args.symbols_file,
            "--interval", args.interval,
            "--limit", str(args.limit),
            "--candles-out", str(candidate_out / "walk_forward_candles.csv"),
            "--out-dir", str(candidate_out),
            "--baseline", str(baseline_path),
            "--profile", args.profile,
            "--windows", str(args.windows),
            "--lookback-days", str(args.lookback_days),
            "--sleep-sec", str(args.sleep_sec),
        ])

        wfo = summarize_wfo(candidate_out / "walk_forward_summary.csv")
        result = {
            "name": name,
            "baseline_path": str(baseline_path),
            "wfo_out_dir": str(candidate_out),
            "matrix_score": to_float(row.get("score")),
            "matrix_ret_pct": to_float(row.get("ret_pct")),
            "matrix_pf": to_float(row.get("pf")),
            "matrix_dd_pct": to_float(row.get("max_dd_pct")),
            "matrix_executed_trades": to_int(row.get("executed_trades")),
            "matrix_allowed_pct": to_float(row.get("allowed_pct")),
            "matrix_sanity_status": row.get("sanity_status", ""),
            "matrix_diagnosis_flags": row.get("diagnosis_flags", ""),
            **wfo,
        }
        result["multi_wfo_score"] = score_candidate(result)
        summary_rows.append(result)

    ranked = sorted(summary_rows, key=lambda r: to_float(r.get("multi_wfo_score")), reverse=True)
    write_csv(out / "tagged_multi_wfo_summary.csv", ranked)
    write_md(out / "tagged_multi_wfo_summary.md", ranked)
    if ranked:
        (out / "tagged_multi_wfo_best.json").write_text(json.dumps(ranked[0], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(out / "tagged_multi_wfo_summary.md")
    print(out / "tagged_multi_wfo_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
