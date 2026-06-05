#!/usr/bin/env python3
"""Promote the best matrix row into a baseline candidate file.

This does not change strategy defaults automatically. It writes a transparent
candidate snapshot so the best research matrix config can be reviewed and then
used for walk-forward validation.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


REQUIRED_COLUMNS = [
    "name",
    "score",
    "rolling_top_n",
    "min_confidence",
    "quality_take_threshold",
    "quality_watch_threshold",
    "structure_take_threshold",
    "structure_watch_threshold",
    "generated_trades",
    "allowed_candidates",
    "allowed_pct",
    "executed_trades",
    "ret_pct",
    "max_dd_pct",
    "pf",
    "winrate",
    "avg_risk_pct",
    "sanity_status",
    "diagnosis_flags",
    "out_dir",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Matrix summary not found: {path}")
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"Matrix summary is empty: {path}")
    return rows


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except (TypeError, ValueError):
        return default


def normalize_row(row: dict[str, str]) -> dict[str, object]:
    return {
        "name": row.get("name", ""),
        "score": to_float(row.get("score")),
        "rolling_top_n": int(to_float(row.get("rolling_top_n"))),
        "min_confidence": to_float(row.get("min_confidence")),
        "quality_take_threshold": to_float(row.get("quality_take_threshold")),
        "quality_watch_threshold": to_float(row.get("quality_watch_threshold")),
        "structure_take_threshold": to_float(row.get("structure_take_threshold")),
        "structure_watch_threshold": to_float(row.get("structure_watch_threshold")),
        "generated_trades": int(to_float(row.get("generated_trades"))),
        "allowed_candidates": int(to_float(row.get("allowed_candidates"))),
        "allowed_pct": to_float(row.get("allowed_pct")),
        "executed_trades": int(to_float(row.get("executed_trades"))),
        "ret_pct": to_float(row.get("ret_pct")),
        "max_dd_pct": to_float(row.get("max_dd_pct")),
        "pf": to_float(row.get("pf")),
        "winrate": to_float(row.get("winrate")),
        "avg_risk_pct": to_float(row.get("avg_risk_pct")),
        "sanity_status": row.get("sanity_status", ""),
        "diagnosis_flags": [flag for flag in row.get("diagnosis_flags", "").split(";") if flag],
        "source_out_dir": row.get("out_dir", ""),
    }


def choose_best(rows: list[dict[str, str]]) -> dict[str, str]:
    return sorted(rows, key=lambda r: to_float(r.get("score")), reverse=True)[0]


def write_markdown(path: Path, candidate: dict[str, object], all_rows: list[dict[str, str]]) -> None:
    lines = [
        "# Baseline Candidate From Matrix",
        "",
        "This file is generated from `matrix_summary.csv`.",
        "It is a research candidate, not a live-trading approval.",
        "",
        "## Candidate",
        f"- Name: **{candidate['name']}**",
        f"- Score: {candidate['score']}",
        f"- Rolling top N: {candidate['rolling_top_n']}",
        f"- Minimum confidence: {candidate['min_confidence']}",
        f"- Quality TAKE threshold: {candidate['quality_take_threshold']}",
        f"- Quality WATCH threshold: {candidate['quality_watch_threshold']}",
        f"- Structure TAKE threshold: {candidate['structure_take_threshold']}",
        f"- Structure WATCH threshold: {candidate['structure_watch_threshold']}",
        "",
        "## Performance snapshot",
        f"- Generated trades: {candidate['generated_trades']}",
        f"- Allowed candidates: {candidate['allowed_candidates']}",
        f"- Allowed pct: {candidate['allowed_pct']}%",
        f"- Executed trades: {candidate['executed_trades']}",
        f"- Return pct: {candidate['ret_pct']}%",
        f"- Max DD pct: {candidate['max_dd_pct']}%",
        f"- PF: {candidate['pf']}",
        f"- Winrate: {candidate['winrate']}%",
        f"- Avg risk pct: {candidate['avg_risk_pct']}",
        f"- Sanity status: {candidate['sanity_status']}",
        f"- Diagnosis flags: {', '.join(candidate['diagnosis_flags']) if candidate['diagnosis_flags'] else 'none'}",
        "",
        "## Review warning",
    ]
    if int(candidate["executed_trades"]) < 10:
        lines.append("- Executed trade count is low. Treat this only as a candidate and run a larger test before promoting defaults.")
    if str(candidate["sanity_status"]) != "OK":
        lines.append("- Sanity status is not OK. Inspect report_sanity_issues.csv before trusting this candidate.")
    if int(candidate["executed_trades"]) >= 10 and str(candidate["sanity_status"]) == "OK":
        lines.append("- Candidate is eligible for walk-forward validation.")

    lines.extend(["", "## Ranked matrix rows"])
    for row in sorted(all_rows, key=lambda r: to_float(r.get("score")), reverse=True):
        lines.append(
            f"- {row.get('name')}: score={row.get('score')}, ret={row.get('ret_pct')}%, "
            f"dd={row.get('max_dd_pct')}%, pf={row.get('pf')}, executed={row.get('executed_trades')}, "
            f"allowed={row.get('allowed_pct')}%, sanity={row.get('sanity_status')}"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote best matrix row to baseline candidate files.")
    parser.add_argument("--matrix", default="results/binance_real_matrix/matrix_summary.csv")
    parser.add_argument("--out-dir", default="results/baseline_candidate")
    args = parser.parse_args()

    matrix_path = Path(args.matrix)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows(matrix_path)
    missing = [col for col in REQUIRED_COLUMNS if col not in rows[0]]
    if missing:
        raise ValueError(f"Matrix summary missing columns: {missing}")

    candidate = normalize_row(choose_best(rows))
    candidate["source_matrix"] = str(matrix_path)

    json_path = out_dir / "baseline_candidate.json"
    md_path = out_dir / "baseline_candidate.md"
    json_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, candidate, rows)

    print("Baseline candidate written")
    print(json_path)
    print(md_path)
    print(f"Candidate: {candidate['name']} score={candidate['score']} sanity={candidate['sanity_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
