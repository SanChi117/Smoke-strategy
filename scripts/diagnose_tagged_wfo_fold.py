#!/usr/bin/env python3
"""Diagnose the weakest fold for the best tagged multi-WFO candidate.

The artifact summaries show which fold is weak, but not why. This script reads
per-fold outputs already produced inside the CI workspace and creates compact
breakdowns by symbol, sector tag, setup/context columns, and close reason when
those columns are available.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


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


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_tags(layer_json: str | Path) -> dict[str, dict[str, Any]]:
    data = load_json(layer_json)
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("symbols", []) or []:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        out[symbol] = {
            "role": row.get("role", "unknown"),
            "sectors": ";".join(row.get("sectors", []) or []),
            "is_core_reference": bool(row.get("is_core_reference", False)),
        }
    return out


def pick_candidate_name(best_json: str | Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    data = load_json(best_json)
    return str(data.get("name", "")).strip()


def pick_weak_fold(summary_rows: list[dict[str, str]], explicit: str | None) -> dict[str, str]:
    if explicit:
        for row in summary_rows:
            if str(row.get("fold", "")) == explicit:
                return row
        raise SystemExit(f"Requested fold not found: {explicit}")
    ok_rows = [r for r in summary_rows if r.get("status") == "OK"] or summary_rows
    if not ok_rows:
        raise SystemExit("No WFO fold rows found")
    return sorted(ok_rows, key=lambda r: (to_float(r.get("ret_pct")), to_float(r.get("pf"))))[0]


def find_candidate_dir(multi_wfo_root: str | Path, candidate_name: str, fold_row: dict[str, str]) -> Path:
    out_dir = str(fold_row.get("out_dir", "")).strip()
    if out_dir:
        p = Path(out_dir).parent
        if p.exists():
            return p
    root = Path(multi_wfo_root)
    p = root / candidate_name
    if p.exists():
        return p
    # Safe fallback for slightly different slug/path names.
    matches = [x for x in root.iterdir() if x.is_dir() and x.name == candidate_name]
    if matches:
        return matches[0]
    raise SystemExit(f"Candidate directory not found: {candidate_name}")


def find_fold_dir(candidate_dir: str | Path, fold_name: str) -> Path:
    p = Path(candidate_dir) / fold_name
    if p.exists():
        return p
    matches = list(Path(candidate_dir).rglob(fold_name))
    for m in matches:
        if m.is_dir():
            return m
    raise SystemExit(f"Fold directory not found: {fold_name} in {candidate_dir}")


def choose_positions_file(fold_dir: str | Path) -> Path | None:
    p = Path(fold_dir)
    preferred = [
        "paper_positions.csv",
        "paper_mode_positions.csv",
        "positions.csv",
    ]
    for name in preferred:
        matches = list(p.rglob(name))
        if matches:
            return matches[0]
    # Find any CSV that has symbol + pnl_pct columns.
    for item in p.rglob("*.csv"):
        rows = read_csv(item)
        if not rows:
            continue
        cols = set(rows[0])
        if "symbol" in cols and "pnl_pct" in cols:
            return item
    return None


def choose_allowed_file(fold_dir: str | Path) -> Path | None:
    p = Path(fold_dir)
    preferred = [
        "pipeline_allowed_trades.csv",
        "allowed_trades.csv",
        "trades_allowed.csv",
    ]
    for name in preferred:
        matches = list(p.rglob(name))
        if matches:
            return matches[0]
    for item in p.rglob("*.csv"):
        rows = read_csv(item)
        if not rows:
            continue
        cols = set(rows[0])
        if "symbol" in cols and any(c in cols for c in ["setup_type", "liquidity_state", "trend_context", "candle_type"]):
            return item
    return None


def enrich(row: dict[str, Any], tags: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbol = str(row.get("symbol", "")).strip().upper()
    tag = tags.get(symbol, {})
    return {
        **row,
        "symbol": symbol,
        "role": tag.get("role", "unknown"),
        "sectors": tag.get("sectors", ""),
        "is_core_reference": tag.get("is_core_reference", False),
    }


def summarize(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    if not rows or key not in rows[0]:
        return []
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_pct": 0.0,
        "gross_win_pct": 0.0,
        "gross_loss_pct": 0.0,
    })
    for row in rows:
        name = str(row.get(key, "") or "unknown")
        pnl = to_float(row.get("pnl_pct"))
        rec = agg[name]
        rec["trades"] += 1
        rec["total_pnl_pct"] += pnl
        if pnl > 0:
            rec["wins"] += 1
            rec["gross_win_pct"] += pnl
        elif pnl < 0:
            rec["losses"] += 1
            rec["gross_loss_pct"] += abs(pnl)
    out = []
    for name, rec in agg.items():
        trades = int(rec["trades"])
        wins = int(rec["wins"])
        gross_loss = float(rec["gross_loss_pct"])
        pf = 99.0 if gross_loss == 0 and rec["gross_win_pct"] > 0 else round(float(rec["gross_win_pct"]) / gross_loss, 6) if gross_loss else 0.0
        out.append({
            key: name,
            "trades": trades,
            "wins": wins,
            "losses": int(rec["losses"]),
            "winrate": round(wins / trades * 100.0, 2) if trades else 0.0,
            "total_pnl_pct": round(float(rec["total_pnl_pct"]), 6),
            "avg_pnl_pct": round(float(rec["total_pnl_pct"]) / trades, 6) if trades else 0.0,
            "pf": pf,
        })
    return sorted(out, key=lambda r: (r["total_pnl_pct"], r["trades"]), reverse=True)


def context_breakdowns(position_rows: list[dict[str, Any]], allowed_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows = position_rows if position_rows else allowed_rows
    keys = [
        "symbol", "role", "sectors", "setup_type", "close_reason", "status",
        "risk_grade", "trend_context", "direction_context", "liquidity_state",
        "candle_type", "volatility_regime",
    ]
    return {key: summarize(rows, key) for key in keys if rows and key in rows[0]}


def write_md(path: str | Path, meta: dict[str, Any], breakdowns: dict[str, list[dict[str, Any]]], rows: list[dict[str, Any]], files: dict[str, str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tagged WFO Fold Diagnostics",
        "",
        f"- Candidate: **{meta.get('candidate')}**",
        f"- Fold: **{meta.get('fold')}**",
        f"- Fold return: {meta.get('ret_pct')}%",
        f"- Fold PF: {meta.get('pf')}",
        f"- Fold DD: {meta.get('max_dd_pct')}%",
        f"- Executed trades: {meta.get('executed_trades')}",
        f"- Sanity: {meta.get('sanity_status')}",
        f"- Flags: {meta.get('diagnosis_flags') or 'none'}",
        "",
        "## Source files",
        f"- positions: {files.get('positions') or 'not found'}",
        f"- allowed/context: {files.get('allowed') or 'not found'}",
        "",
    ]
    if not rows:
        lines.append("No position-level rows were found in the current artifact/workspace. Upload/export per-fold CSVs to get symbol/setup diagnostics.")
    else:
        lines.append(f"Rows diagnosed: {len(rows)}")
        lines.append("")
    for key in ["symbol", "sectors", "setup_type", "close_reason", "liquidity_state", "trend_context", "direction_context", "candle_type", "volatility_regime", "risk_grade", "role"]:
        data = breakdowns.get(key) or []
        if not data:
            continue
        lines.append(f"## Breakdown by {key}")
        lines.append("")
        for row in data[:25]:
            label = row.get(key)
            lines.append(
                f"- **{label}**: trades={row['trades']}, winrate={row['winrate']}%, "
                f"total={row['total_pnl_pct']}%, avg={row['avg_pnl_pct']}%, pf={row['pf']}"
            )
        lines.append("")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose weakest fold for tagged multi-WFO candidate.")
    ap.add_argument("--multi-wfo-root", default="results/tagged_universe_research/multi_wfo")
    ap.add_argument("--best-json", default="results/tagged_universe_research/multi_wfo/tagged_multi_wfo_best.json")
    ap.add_argument("--candidate", default=None)
    ap.add_argument("--fold", default=None)
    ap.add_argument("--layer-json", default="results/strategy_universe_layer/strategy_universe_layer.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/fold_diagnostics")
    args = ap.parse_args()

    candidate = pick_candidate_name(args.best_json, args.candidate)
    if not candidate:
        raise SystemExit("Candidate name is empty. Provide --candidate or a valid best json.")
    tags = load_tags(args.layer_json)

    summary_path = Path(args.multi_wfo_root) / candidate / "walk_forward_summary.csv"
    summary_rows = read_csv(summary_path)
    weak = pick_weak_fold(summary_rows, args.fold)
    fold_name = str(weak.get("fold", "")).strip()
    candidate_dir = find_candidate_dir(args.multi_wfo_root, candidate, weak)
    fold_dir = find_fold_dir(candidate_dir, fold_name)

    positions_file = choose_positions_file(fold_dir)
    allowed_file = choose_allowed_file(fold_dir)
    positions = [enrich(r, tags) for r in read_csv(positions_file)] if positions_file else []
    allowed = [enrich(r, tags) for r in read_csv(allowed_file)] if allowed_file else []

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "candidate": candidate,
        "fold": fold_name,
        "summary_path": str(summary_path),
        "fold_dir": str(fold_dir),
        **weak,
    }
    (out / "fold_diagnostics_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if positions:
        write_csv(out / "fold_positions_enriched.csv", positions)
    if allowed:
        write_csv(out / "fold_allowed_trades_enriched.csv", allowed)
    rows_for_breakdown = positions if positions else allowed
    breakdowns = context_breakdowns(positions, allowed)
    for key, rows in breakdowns.items():
        write_csv(out / f"breakdown_by_{key}.csv", rows)
    write_md(
        out / "fold_diagnostics.md",
        meta,
        breakdowns,
        rows_for_breakdown,
        {"positions": str(positions_file) if positions_file else "", "allowed": str(allowed_file) if allowed_file else ""},
    )
    print(out / "fold_diagnostics.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
