#!/usr/bin/env python3
"""Diagnose weak folds from tagged deep validation.

Deep validation can fail even when short multi-WFO passes. This script analyzes
all negative deep-validation folds (or the worst N folds) using per-fold CSVs.

The important part: paper_positions.csv contains the actual PnL/close reason,
while pipeline_allowed_trades.csv contains the entry context. This script merges
them by symbol+side+entry_time, then breaks down both all weak-fold rows and only
stop-loss rows by symbol, sector, setup and context.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


def read_csv(path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
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


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_symbol(value: Any) -> str:
    return clean(value).upper()


def normalize_side(value: Any) -> str:
    return clean(value).lower()


def normalize_time(value: Any) -> str:
    text = clean(value)
    if text.endswith("Z"):
        text = text[:-1]
    return text.replace(" ", "T")


def merge_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (normalize_symbol(row.get("symbol")), normalize_side(row.get("side")), normalize_time(row.get("entry_time")))


def parse_risk_plan(reason: Any) -> dict[str, Any]:
    """Parse pipe-separated risk_plan_reason fields.

    Example:
    setup=pullback|side=short|trend=trend|dir=down|structure=trend_pullback|vol=normal|...
    """
    text = clean(reason)
    parsed: dict[str, Any] = {}
    if not text:
        return parsed
    for part in text.split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[clean(key)] = clean(value)

    mapped = {
        "direction_context": parsed.get("dir", ""),
        "candle_type": parsed.get("candle", ""),
        "liquidity_state": parsed.get("liq", ""),
        "volatility_regime": parsed.get("vol", ""),
        "volume_ratio": parsed.get("vr", ""),
        "volume_state": parsed.get("vol_state", ""),
        "range_position": parsed.get("pos", ""),
        "quality_score": parsed.get("quality", ""),
        "risk_plan_setup": parsed.get("setup", ""),
        "risk_plan_side": parsed.get("side", ""),
        "risk_plan_trend": parsed.get("trend", ""),
        "risk_plan_structure": parsed.get("structure", ""),
        "risk_plan_policy": parsed.get("policy", ""),
        "risk_plan_rr": parsed.get("rr", ""),
        "risk_plan_stop_pct": parsed.get("stop_pct", ""),
    }
    return {k: v for k, v in mapped.items() if v not in {None, ""}}


def normalize_allowed_context(row: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_risk_plan(row.get("risk_plan_reason"))
    context = dict(row)
    for key, value in parsed.items():
        if not clean(context.get(key)):
            context[key] = value
    # Backfill common context names from allowed-trades columns.
    if not clean(context.get("close_reason")) and clean(context.get("exit_reason")):
        context["close_reason"] = context.get("exit_reason")
    if not clean(context.get("signal_side")) and clean(context.get("side")):
        context["signal_side"] = context.get("side")
    return context


def context_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], deque[dict[str, Any]]]:
    idx: dict[tuple[str, str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for row in rows:
        ctx = normalize_allowed_context(row)
        idx[merge_key(ctx)].append(ctx)
    return idx


def load_tags(layer_json: str | Path) -> dict[str, dict[str, Any]]:
    data = load_json(layer_json)
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("symbols", []) or []:
        symbol = normalize_symbol(row.get("symbol"))
        if not symbol:
            continue
        out[symbol] = {
            "role": row.get("role", "unknown"),
            "sectors": ";".join(row.get("sectors", []) or []),
            "is_core_reference": bool(row.get("is_core_reference", False)),
        }
    return out


def enrich_tags(row: dict[str, Any], tags: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbol = normalize_symbol(row.get("symbol"))
    tag = tags.get(symbol, {})
    return {
        **row,
        "symbol": symbol,
        "role": tag.get("role", "unknown"),
        "sectors": tag.get("sectors", ""),
        "is_core_reference": tag.get("is_core_reference", False),
    }


def merge_position_with_context(position: dict[str, Any], ctx: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(position)
    if ctx:
        for key, value in ctx.items():
            if key in {"symbol", "side", "entry_time", "exit_time", "entry", "exit", "stop"}:
                continue
            if key not in merged or clean(merged.get(key)) == "":
                merged[key] = value
            else:
                merged[f"allowed_{key}"] = value
        merged["context_merged"] = True
    else:
        merged["context_merged"] = False
    if not clean(merged.get("signal_side")) and clean(merged.get("side")):
        merged["signal_side"] = merged.get("side")
    return merged


def merge_rows(positions: list[dict[str, Any]], allowed: list[dict[str, Any]], tags: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not positions:
        return [enrich_tags(normalize_allowed_context(r), tags) for r in allowed]
    idx = context_index(allowed)
    merged: list[dict[str, Any]] = []
    for pos in positions:
        key = merge_key(pos)
        ctx = idx[key].popleft() if idx.get(key) else None
        merged.append(enrich_tags(merge_position_with_context(pos, ctx), tags))
    return merged


def choose_positions_file(fold_dir: str | Path) -> Path | None:
    p = Path(fold_dir)
    preferred = ["paper_positions.csv", "paper_mode_positions.csv", "positions.csv"]
    for name in preferred:
        matches = list(p.rglob(name))
        if matches:
            return matches[0]
    for item in p.rglob("*.csv"):
        rows = read_csv(item)
        if rows and "symbol" in rows[0] and "pnl_pct" in rows[0]:
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
        if "symbol" in cols and any(c in cols for c in ["setup_type", "liquidity_state", "trend_context", "candle_type", "risk_plan_reason"]):
            return item
    return None


def find_fold_dir(root: str | Path, fold_name: str, row: dict[str, str]) -> Path | None:
    out_dir = clean(row.get("out_dir"))
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
        "stop_losses": 0,
        "total_pnl_pct": 0.0,
        "gross_win_pct": 0.0,
        "gross_loss_pct": 0.0,
    })
    for row in rows:
        name = clean(row.get(key)) or "unknown"
        pnl = to_float(row.get("pnl_pct"))
        rec = agg[name]
        rec["trades"] += 1
        rec["total_pnl_pct"] += pnl
        if clean(row.get("close_reason")) == "stop_loss" or clean(row.get("exit_reason")) == "stop_loss":
            rec["stop_losses"] += 1
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
        stop_losses = int(rec["stop_losses"])
        gross_loss = float(rec["gross_loss_pct"])
        pf = 99.0 if gross_loss == 0 and rec["gross_win_pct"] > 0 else round(float(rec["gross_win_pct"]) / gross_loss, 6) if gross_loss else 0.0
        out.append({
            key: name,
            "trades": trades,
            "wins": wins,
            "losses": int(rec["losses"]),
            "stop_losses": stop_losses,
            "stop_loss_pct": round(stop_losses / trades * 100.0, 2) if trades else 0.0,
            "winrate": round(wins / trades * 100.0, 2) if trades else 0.0,
            "total_pnl_pct": round(float(rec["total_pnl_pct"]), 6),
            "avg_pnl_pct": round(float(rec["total_pnl_pct"]) / trades, 6) if trades else 0.0,
            "pf": pf,
        })
    return sorted(out, key=lambda r: (r["total_pnl_pct"], -r["stop_losses"], r["trades"]), reverse=True)


def write_breakdowns(out_dir: Path, prefix: str, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    keys = [
        "symbol", "role", "sectors", "setup_type", "close_reason", "exit_reason", "status",
        "risk_grade", "trend_context", "direction_context", "liquidity_state",
        "candle_type", "volatility_regime", "volume_state", "volume_ratio",
        "range_position", "quality_score", "structure_type", "target_policy", "side", "signal_side",
    ]
    out: dict[str, list[dict[str, Any]]] = {}
    available = set().union(*(set(r.keys()) for r in rows)) if rows else set()
    for key in keys:
        if key in available:
            data = summarize(rows, key)
            out[key] = data
            write_csv(out_dir / f"{prefix}_breakdown_by_{key}.csv", data)
    return out


def stop_loss_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if clean(r.get("close_reason")) == "stop_loss" or clean(r.get("exit_reason")) == "stop_loss"]


def write_md(
    path: str | Path,
    candidate: str,
    weak_folds: list[dict[str, str]],
    fold_outputs: list[dict[str, Any]],
    aggregate_breakdowns: dict[str, list[dict[str, Any]]],
    stop_breakdowns: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [
        "# Tagged Deep Validation Fold Diagnostics",
        "",
        f"- Candidate: **{candidate or 'UNKNOWN'}**",
        f"- Weak folds diagnosed: {', '.join(str(f.get('fold')) for f in weak_folds)}",
        "- Context merge: positions + pipeline_allowed_trades by symbol/side/entry_time",
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
            f"- context merged rows: {item.get('context_merged_rows', 0)}",
            f"- stop-loss rows: {item.get('stop_loss_rows', 0)}",
            "",
        ])
    lines.append("## Aggregate weak-fold breakdowns")
    lines.append("")
    for key in ["symbol", "sectors", "setup_type", "close_reason", "liquidity_state", "trend_context", "direction_context", "candle_type", "volatility_regime", "volume_state", "quality_score", "range_position", "role", "side", "signal_side"]:
        rows = aggregate_breakdowns.get(key) or []
        if not rows:
            continue
        lines.append(f"### By {key}")
        for row in rows[:30]:
            label = row.get(key)
            lines.append(
                f"- **{label}**: trades={row['trades']}, stop_loss={row['stop_losses']} ({row['stop_loss_pct']}%), "
                f"winrate={row['winrate']}%, total={row['total_pnl_pct']}%, avg={row['avg_pnl_pct']}%, pf={row['pf']}"
            )
        lines.append("")
    lines.append("## Stop-loss-only breakdowns")
    lines.append("")
    for key in ["symbol", "sectors", "setup_type", "liquidity_state", "trend_context", "direction_context", "candle_type", "volatility_regime", "volume_state", "quality_score", "range_position", "role", "side", "signal_side"]:
        rows = stop_breakdowns.get(key) or []
        if not rows:
            continue
        lines.append(f"### Stop-loss by {key}")
        for row in rows[:30]:
            label = row.get(key)
            lines.append(
                f"- **{label}**: stops={row['trades']}, total={row['total_pnl_pct']}%, avg={row['avg_pnl_pct']}%"
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
    candidate = clean(deep_summary.get("candidate")) or clean(deep_summary.get("baseline", {}).get("name"))
    rows = read_csv(args.walk_forward)
    if not rows:
        raise SystemExit(f"No deep walk-forward rows found: {args.walk_forward}")
    weak = select_weak_folds(rows, args.max_folds)
    tags = load_tags(args.layer_json)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    all_stop_rows: list[dict[str, Any]] = []
    fold_outputs: list[dict[str, Any]] = []
    for fold in weak:
        fold_name = clean(fold.get("fold"))
        fold_dir = find_fold_dir(args.deep_root, fold_name, fold)
        positions_file = choose_positions_file(fold_dir) if fold_dir else None
        allowed_file = choose_allowed_file(fold_dir) if fold_dir else None
        positions = read_csv(positions_file)
        allowed = read_csv(allowed_file)
        diagnosed = merge_rows(positions, allowed, tags)
        stops = stop_loss_rows(diagnosed)
        all_rows.extend(diagnosed)
        all_stop_rows.extend(stops)
        prefix = fold_name or "fold"
        if diagnosed:
            write_csv(out / f"{prefix}_rows_enriched.csv", diagnosed)
            write_breakdowns(out, prefix, diagnosed)
        if stops:
            write_csv(out / f"{prefix}_stop_loss_rows_enriched.csv", stops)
            write_breakdowns(out, f"{prefix}_stop_loss", stops)
        context_merged_count = sum(1 for r in diagnosed if r.get("context_merged") is True)
        fold_outputs.append({
            "fold": fold_name,
            "fold_dir": str(fold_dir) if fold_dir else "",
            "positions_file": str(positions_file) if positions_file else "",
            "allowed_file": str(allowed_file) if allowed_file else "",
            "positions_rows": len(positions),
            "allowed_rows": len(allowed),
            "rows_diagnosed": len(diagnosed),
            "context_merged_rows": context_merged_count,
            "stop_loss_rows": len(stops),
            "summary": fold,
        })

    write_csv(out / "weak_folds_selected.csv", weak)
    write_csv(out / "deep_weak_folds_rows_enriched.csv", all_rows)
    write_csv(out / "deep_weak_folds_stop_loss_rows_enriched.csv", all_stop_rows)
    aggregate = write_breakdowns(out, "aggregate_weak_folds", all_rows)
    stop_aggregate = write_breakdowns(out, "aggregate_stop_loss", all_stop_rows)
    meta = {
        "candidate": candidate,
        "deep_root": str(args.deep_root),
        "weak_folds": weak,
        "fold_outputs": fold_outputs,
    }
    (out / "deep_fold_diagnostics_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out / "deep_fold_diagnostics.md", candidate, weak, fold_outputs, aggregate, stop_aggregate)
    print(out / "deep_fold_diagnostics.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
