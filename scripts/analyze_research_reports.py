#!/usr/bin/env python3
"""Analyze Smoke Strategy research reports and write a compact diagnosis.

The analyzer is intentionally conservative. It does not prove profitability;
it highlights whether the current research run is usable, too sparse, over-filtered,
or weak enough that strategy logic should be adjusted before any paper/live step.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_metrics(path: Path) -> dict[str, str]:
    rows = read_rows(path)
    out: dict[str, str] = {}
    for row in rows:
        metric = row.get("metric")
        if metric:
            out[metric] = row.get("value", "")
    return out


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except (TypeError, ValueError):
        return default


def to_int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value if value not in {None, ""} else default))
    except (TypeError, ValueError):
        return default


def pct(part: int, total: int) -> float:
    return round(part / total * 100.0, 2) if total else 0.0


def reason_counts(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter(row.get("reason", "unknown") or "unknown" for row in rows)


def top_values(rows: list[dict[str, str]], field: str, limit: int = 8) -> list[tuple[str, int]]:
    return Counter(row.get(field, "unknown") or "unknown" for row in rows).most_common(limit)


def build_diagnosis(out_dir: Path) -> tuple[str, list[str]]:
    end = read_first(out_dir / "end_to_end_summary.csv")
    sanity = read_first(out_dir / "report_sanity_summary.csv")
    candle = read_metrics(out_dir / "candle_research_report.csv")
    pipeline = read_first(out_dir / "pipeline_summary.csv")
    paper = read_first(out_dir / "paper" / "paper_decision_summary.csv")
    decisions = read_rows(out_dir / "pipeline_decisions.csv")
    issues = read_rows(out_dir / "report_sanity_issues.csv")

    candidates = to_int(end.get("generated_trades") or pipeline.get("candidates"))
    allowed = to_int(end.get("allowed_candidates") or pipeline.get("allowed_candidates"))
    executed = to_int(end.get("executed_trades") or pipeline.get("executed_trades"))
    ret_pct = to_float(end.get("ret_pct") or pipeline.get("ret_pct"))
    max_dd_pct = to_float(end.get("max_dd_pct") or pipeline.get("max_dd_pct"))
    pf = to_float(end.get("pf") or pipeline.get("pf"))
    winrate = to_float(end.get("winrate") or pipeline.get("winrate"))
    avg_risk_pct = to_float(end.get("avg_risk_pct") or pipeline.get("avg_risk_pct"))
    candle_avg_r = to_float(candle.get("avg_r"))
    time_stop_count = to_float(candle.get("time_stop_count"))
    simulated_exits = max(1, to_int(candle.get("simulated_exits"), 1))
    time_stop_pct = round(time_stop_count / simulated_exits * 100.0, 2)
    sanity_status = (sanity.get("status") or end.get("sanity_status") or "UNKNOWN").upper()
    paper_decision = (paper.get("decision") or "UNKNOWN").upper()

    flags: list[str] = []
    recommendations: list[str] = []

    if candidates < 20:
        flags.append("TOO_FEW_SETUPS")
        recommendations.append("Increase history length, broaden symbols, or lower setup generation strictness before judging performance.")
    if allowed == 0 and candidates > 0:
        flags.append("ALL_TRADES_FILTERED")
        recommendations.append("Rolling/quality/structure gates are blocking everything; inspect pipeline_decisions.csv reasons.")
    elif candidates > 0 and pct(allowed, candidates) < 5:
        flags.append("OVER_FILTERED")
        recommendations.append("Allowed rate is very low; consider relaxing rolling_top_n, quality SKIP, or structure SKIP thresholds.")
    if executed == 0 and allowed > 0:
        flags.append("PORTFOLIO_NOT_EXECUTING")
        recommendations.append("Allowed trades exist but portfolio simulator executed none; inspect max positions, cash, and overlap constraints.")
    if executed < 10:
        flags.append("TOO_FEW_EXECUTED")
        recommendations.append("Executed trade count is too small for statistical conclusions; run more candles and symbols.")
    if pf > 0 and pf < 1.1:
        flags.append("LOW_PROFIT_FACTOR")
        recommendations.append("Profit factor is weak; inspect setup_type and exit_reason diagnostics before increasing risk.")
    if candle_avg_r < 0:
        flags.append("NEGATIVE_AVG_R")
        recommendations.append("Candle simulation average R is negative; prioritize entry/exit logic before portfolio tuning.")
    if time_stop_pct > 50:
        flags.append("TOO_MANY_TIME_STOPS")
        recommendations.append("Too many trades exit by time stop; improve target realism, timeout rules, or setup timing.")
    if ret_pct <= 0 and executed > 0:
        flags.append("NEGATIVE_RETURN")
        recommendations.append("Portfolio return is non-positive; break down losses by setup_type, trend_context, and volatility_regime.")
    if max_dd_pct < -10:
        flags.append("HIGH_DRAWDOWN")
        recommendations.append("Drawdown is high for research profile; reduce risk or strengthen filters.")
    if sanity_status == "FAIL":
        flags.append("SANITY_FAIL")
        recommendations.append("Do not trust this run until report_sanity_issues.csv errors are fixed.")
    elif sanity_status == "WARN":
        flags.append("SANITY_WARN")
        recommendations.append("Treat this run as review-only; inspect warnings before changing risk.")
    if paper_decision == "BLOCK":
        flags.append("PAPER_BLOCK")
        recommendations.append("Paper decision blocks the run; inspect paper/paper_review.csv before further optimization.")

    if not flags:
        flags.append("RESEARCH_RUN_USABLE")
        recommendations.append("Run a larger multi-symbol test and walk-forward validation before trusting the strategy.")

    reasons = reason_counts(decisions)
    lines: list[str] = []
    lines.append("# Smoke Strategy Research Diagnosis")
    lines.append("")
    lines.append("## Verdict")
    if "SANITY_FAIL" in flags or "PAPER_BLOCK" in flags:
        verdict = "BLOCK"
    elif any(flag in flags for flag in ["TOO_FEW_SETUPS", "TOO_FEW_EXECUTED", "OVER_FILTERED", "SANITY_WARN"]):
        verdict = "WATCH"
    else:
        verdict = "PASS_FOR_RESEARCH_REVIEW"
    lines.append(f"- Verdict: **{verdict}**")
    lines.append(f"- Flags: {', '.join(flags)}")
    lines.append("")

    lines.append("## Core metrics")
    metrics = [
        ("sanity_status", sanity_status),
        ("paper_decision", paper_decision),
        ("generated_trades", candidates),
        ("allowed_candidates", allowed),
        ("allowed_pct", f"{pct(allowed, candidates)}%"),
        ("executed_trades", executed),
        ("ret_pct", f"{ret_pct}%"),
        ("max_dd_pct", f"{max_dd_pct}%"),
        ("pf", pf),
        ("winrate", f"{winrate}%"),
        ("avg_risk_pct", avg_risk_pct),
        ("candle_avg_r", candle_avg_r),
        ("time_stop_pct", f"{time_stop_pct}%"),
    ]
    for key, value in metrics:
        lines.append(f"- {key}: {value}")
    lines.append("")

    if reasons:
        lines.append("## Decision reasons")
        for reason, count in reasons.most_common(12):
            lines.append(f"- {reason}: {count} ({pct(count, len(decisions))}%)")
        lines.append("")

    for field, title in [
        ("setup_type", "Setup types"),
        ("trend_context", "Trend contexts"),
        ("volatility_regime", "Volatility regimes"),
        ("quality_decision", "Quality decisions"),
        ("structure_decision", "Structure decisions"),
    ]:
        values = top_values(decisions, field)
        if values:
            lines.append(f"## {title}")
            for value, count in values:
                lines.append(f"- {value}: {count}")
            lines.append("")

    if issues:
        lines.append("## Sanity issues")
        for row in issues[:20]:
            lines.append(f"- {row.get('level', '')}: {row.get('check', '')} / {row.get('metric', '')} = {row.get('value', '')}; {row.get('message', '')}")
        lines.append("")

    lines.append("## Recommendations")
    for item in recommendations:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Next research step")
    if "OVER_FILTERED" in flags or "ALL_TRADES_FILTERED" in flags:
        lines.append("- Run a parameter comparison for rolling_top_n and quality/structure thresholds.")
    elif "TOO_FEW_EXECUTED" in flags or "TOO_FEW_SETUPS" in flags:
        lines.append("- Increase candles limit to 1000-1500 and expand the universe to 10-20 liquid symbols.")
    elif "NEGATIVE_AVG_R" in flags or "LOW_PROFIT_FACTOR" in flags:
        lines.append("- Break down performance by setup_type and exit_reason, then disable the weakest setup family.")
    else:
        lines.append("- Proceed to walk-forward validation on the same real-data source.")

    return "\n".join(lines) + "\n", flags


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Smoke Strategy research reports.")
    parser.add_argument("--out-dir", default="results/binance_real", help="Research output directory")
    parser.add_argument("--output", default=None, help="Diagnosis markdown output path")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    output = Path(args.output) if args.output else out_dir / "research_diagnosis.md"
    diagnosis, flags = build_diagnosis(out_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(diagnosis, encoding="utf-8")
    print(diagnosis)
    return 1 if "SANITY_FAIL" in flags or "PAPER_BLOCK" in flags else 0


if __name__ == "__main__":
    raise SystemExit(main())
