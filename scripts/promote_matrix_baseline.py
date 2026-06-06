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


FILTER_COLUMNS = [
    "allowed_symbols_filter",
    "blocked_symbols_filter",
    "allowed_setup_types_filter",
    "blocked_setup_types_filter",
    "allowed_trend_contexts_filter",
    "blocked_trend_contexts_filter",
    "allowed_volatility_regimes_filter",
    "blocked_volatility_regimes_filter",
    "allowed_liquidity_states_filter",
    "blocked_liquidity_states_filter",
    "allowed_candle_types_filter",
    "blocked_candle_types_filter",
    "allowed_direction_contexts_filter",
    "blocked_direction_contexts_filter",
]

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


def to_bool(value: str | None, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def split_filter(value: str | None) -> list[str]:
    if value is None:
        return []
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def normalize_row(row: dict[str, str]) -> dict[str, object]:
    candidate = {
        "name": row.get("name", ""),
        "score": to_float(row.get("score")),
        "rolling_top_n": int(to_float(row.get("rolling_top_n"))),
        "require_rolling_top": to_bool(row.get("require_rolling_top"), True),
        "require_universe_gate": to_bool(row.get("require_universe_gate"), True),
        "min_confidence": to_float(row.get("min_confidence")),
        "quality_take_threshold": to_float(row.get("quality_take_threshold")),
        "quality_watch_threshold": to_float(row.get("quality_watch_threshold")),
        "structure_take_threshold": to_float(row.get("structure_take_threshold")),
        "structure_watch_threshold": to_float(row.get("structure_watch_threshold")),
        "min_volume_ratio": to_float(row.get("min_volume_ratio"), 0.0),
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
    for col in FILTER_COLUMNS:
        json_key = col.replace("_filter", "")
        candidate[json_key] = split_filter(row.get(col))
    return candidate


def choose_best(rows: list[dict[str, str]]) -> dict[str, str]:
    return sorted(rows, key=lambda r: to_float(r.get("score")), reverse=True)[0]


def list_value(candidate: dict[str, object], key: str) -> str:
    return ", ".join(candidate.get(key, [])) or "none"


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
        f"- Require rolling top: {candidate['require_rolling_top']}",
        f"- Require universe gate: {candidate['require_universe_gate']}",
        f"- Minimum confidence: {candidate['min_confidence']}",
        f"- Quality TAKE threshold: {candidate['quality_take_threshold']}",
        f"- Quality WATCH threshold: {candidate['quality_watch_threshold']}",
        f"- Structure TAKE threshold: {candidate['structure_take_threshold']}",
        f"- Structure WATCH threshold: {candidate['structure_watch_threshold']}",
        f"- Minimum volume ratio: {candidate['min_volume_ratio']}",
        "",
        "## Tactical filters",
        f"- Allowed symbols: {list_value(candidate, 'allowed_symbols')}",
        f"- Blocked symbols: {list_value(candidate, 'blocked_symbols')}",
        f"- Allowed setup types: {list_value(candidate, 'allowed_setup_types')}",
        f"- Blocked setup types: {list_value(candidate, 'blocked_setup_types')}",
        f"- Allowed trend contexts: {list_value(candidate, 'allowed_trend_contexts')}",
        f"- Blocked trend contexts: {list_value(candidate, 'blocked_trend_contexts')}",
        f"- Allowed volatility regimes: {list_value(candidate, 'allowed_volatility_regimes')}",
        f"- Blocked volatility regimes: {list_value(candidate, 'blocked_volatility_regimes')}",
        f"- Allowed liquidity states: {list_value(candidate, 'allowed_liquidity_states')}",
        f"- Blocked liquidity states: {list_value(candidate, 'blocked_liquidity_states')}",
        f"- Allowed candle types: {list_value(candidate, 'allowed_candle_types')}",
        f"- Blocked candle types: {list_value(candidate, 'blocked_candle_types')}",
        f"- Allowed direction contexts: {list_value(candidate, 'allowed_direction_contexts')}",
        f"- Blocked direction contexts: {list_value(candidate, 'blocked_direction_contexts')}",
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
            f"allowed={row.get('allowed_pct')}%, min_vr={row.get('min_volume_ratio', '')}, "
            f"rolling_required={row.get('require_rolling_top', '')}, universe_required={row.get('require_universe_gate', '')}, "
            f"sanity={row.get('sanity_status')}"
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
