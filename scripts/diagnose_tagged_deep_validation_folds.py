#!/usr/bin/env python3
"""Diagnose weak folds from tagged deep validation.

Deep validation can fail even when short multi-WFO passes. This script analyzes
all negative deep-validation folds (or the worst N folds) using per-fold CSVs
available in the CI workspace and creates breakdowns by symbol, sector tag,
setup/context, and close reason when those columns are available.

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


def load_json(path: str | Path) -> dict[str, Any]:
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


def choose_positions_file(fold_dir: str | Path) -> Path | None:
    p = Path(fold_dir)
    preferred = ["paper_positions.csv", "paper_mode_positions.csv", "positions.csv"]
    for name in preferred:
        matches = list(p.rglob(name))
        if matches:
            return matches[0]
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
    preferred = ["pipeline_allowed_trades.csv", "allowed_trades.csv", "trades_allowed.csv"]
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


def find_fold_dir(root: str | Path, fold_name: str, row: dict[str, str]) -> Path | None:
    out_dir = str(row.get("out_dir", "")).strip()
    if out_dir:
        p = Path(out_dir)
        if p.is_dir():
            return p
        if p.parent.is_dir():
            return p.parent
    root_p = Path(root)
    candidate = root_p / fold_name
    if candidate.exists():
        return candidate
    for p in root_p.rglob(fold_name):
        if p.is_dir():
            return p
    return None


def select_weak_folds(rows: list[dict[str, str]], max_folds: int) -> list[dict[str, str]]:
    ok_rows = [r for r in rows if r.get("status") == "OK"] or rows
    negative = [r for r in ok_rows if to_float(r.get("ret_pct")) < 0]
    selected = negative if negative else sorted(ok_rows, key=lambda r: to_float(r.get("ret_pct")))[:max_folds]
    return sorted(selected, key=lambda r: to_float(r.get("ret_pct")))[:max_folds]


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


def write_breakdowns(out_dir: Path, prefix: str, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    keys = [
        "symbol", "role", "sectors", "setup_type", "close_reason", "status",
        "risk_grade", "trend_context", "direction_context", "liquidity_state",
        "candle_type", "volatility_regime", "side", "signal_side",
    ]
    out: dict[str, list[dict[str, Any]]] = {}
    for key in keys:
        if rows and key in rows[0]:
            data = summarize(rows, key)
            out[key] = data
            write_csv(out_dir / f"{prefix}_breakdown_by_{key}.csv", data)
    return out


def write_md(path: str | Path, candidate: str, weak_folds: list[dict[str, str]], fold_outputs: list[dict[str, Any]], aggregate_breakdowns: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        "# Tagged Deep Validation Fold Diagnostics",
        "",
        f"- Candidate: **{candidate or 'UNKNOWN'}**",
        f"- Weak folds diagnosed: {', '.join(str(f.get('fold')) for f in weak_folds)}",
        "",
        "## Weak fold summary",
        "",
    ]
    for row in weak_folds:
        lines.append(
            f"- **{row.get('fold')}**: ret={row.get('ret_pct')}%, pf={row.get('pf')}, "
            f"dd={row.get('max_dd_pct')}%, executed={row.get('executed_trades')}, sanity={row.get('sanity_status')}"
        )
    lines.append("")
    for item in fold_outputs:
        lines.extend([
            f"## {item['fold']} source files",
            "",
            f"- fold_dir: {item.get('fold_dir') or 'not found'}",
            f"- positions: {item.get('positions_file') or 'not found'}",
            f"- allowed/context: {item.get('allowed_file') or 'not found'}",
            f"- rows diagnosed: {item.get('rows_diagnosed', 0)}",
            "",
        ])
    lines.append("## Aggregate weak-fold breakdowns")
    lines.append("")
    for key in ["symbol", "sectors", "setup_type", "close_reason", "liquidity_state", "trend_context", "direction_context", "candle_type", "volatility_regime", "role", "side", "signal_side"]:
        rows = aggregate_breakdowns.get(key) or []
        if not rows:
            continue
        lines.append(f"### By {key}")
        for row in rows[:30]:
            label = row.get(key)
            lines.append(
                f"- **{label}**: trades={row['trades']}, winrate={row['winrate']}%, "
                f"total={row['total_pnl_pct']}%, avg={row['avg_pnl_pct']}%, pf={row['pf']}"
            )
        lines.append("")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose negative deep-validation folds.")
    ap.add_argument("--deep-root", default="results/tagged_universe_research/deep_validation")
    ap.add_argument("--deep-summary", default="results/tagged_universe_research/deep_validation/deep_validation_summary.json")
    ap.add_argument("--walk-forward", default="results/tagged_universe_research/deep_validation/walk_forward_summary.csv")
    ap.add_argument("--layer-json", default="results/strategy_universe_layer/strategy_universe_layer.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/deep_fold_diagnostics")
    ap.add_argument("--max-folds", type=int, default=6)
    args = ap.parse_args()

    deep_summary = load_json(args.deep_summary)
    candidate = str(deep_summary.get("candidate", "") or deep_summary.get("baseline", {}).get("name", ""))
    rows = read_csv(args.walk_forward)
    if not rows:
        raise SystemExit(f"No deep walk-forward rows found: {args.walk_forward}")
    weak = select_weak_folds(rows, args.max_folds)
    tags = load_tags(args.layer_json)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    fold_outputs: list[dict[str, Any]] = []
    for fold in weak:
        fold_name = str(fold.get("fold", "")).strip()
        fold_dir = find_fold_dir(args.deep_root, fold_name, fold)
        positions_file = choose_positions_file(fold_dir) if fold_dir else None
        allowed_file = choose_allowed_file(fold_dir) if fold_dir else None
        positions = [enrich(r, tags) for r in read_csv(positions_file)] if positions_file else []
        allowed = [enrich(r, tags) for r in read_csv(allowed_file)] if allowed_file else []
        diagnosed = positions if positions else allowed
        all_rows.extend(diagnosed)
        prefix = fold_name or "fold"
        if diagnosed:
            write_csv(out / f"{prefix}_rows_enriched.csv", diagnosed)
            write_breakdowns(out, prefix, diagnosed)
        fold_outputs.append({
            "fold": fold_name,
            "fold_dir": str(fold_dir) if fold_dir else "",
            "positions_file": str(positions_file) if positions_file else "",
            "allowed_file": str(allowed_file) if allowed_file else "",
            "rows_diagnosed": len(diagnosed),
            "summary": fold,
        })

    write_csv(out / "weak_folds_selected.csv", weak)
    write_csv(out / "deep_weak_folds_rows_enriched.csv", all_rows)
    aggregate = write_breakdowns(out, "aggregate_weak_folds", all_rows)
    meta = {
        "candidate": candidate,
        "deep_root": str(args.deep_root),
        "weak_folds": weak,
        "fold_outputs": fold_outputs,
    }
    (out / "deep_fold_diagnostics_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out / "deep_fold_diagnostics.md", candidate, weak, fold_outputs, aggregate)
    print(out / "deep_fold_diagnostics.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
