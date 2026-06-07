#!/usr/bin/env python3
"""Summarize which symbols the tagged-universe strategy actually selected.

Reads matrix config paper positions and attaches role/sector tags from the
strategy universe layer. Produces compact CSV/MD artifacts so the heavy per-run
files do not need to be uploaded.

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


def load_tags(layer_json: str | Path) -> dict[str, dict[str, Any]]:
    p = Path(layer_json)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
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


def collect_positions(matrix_root: str | Path, tags: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    root = Path(matrix_root)
    matrix_rows = read_csv(root / "matrix_summary.csv")
    rows: list[dict[str, Any]] = []
    for matrix_row in matrix_rows:
        config = str(matrix_row.get("name", "")).strip()
        if not config:
            continue
        fixed_allowlist = bool(str(matrix_row.get("allowed_symbols_filter", "")).strip())
        positions = read_csv(root / config / "paper" / "paper_positions.csv")
        for pos in positions:
            symbol = str(pos.get("symbol", "")).strip().upper()
            tag = tags.get(symbol, {})
            rows.append({
                **pos,
                "config": config,
                "fixed_allowlist_config": fixed_allowlist,
                "role": tag.get("role", "unknown"),
                "sectors": tag.get("sectors", ""),
                "is_core_reference": tag.get("is_core_reference", False),
            })
    return rows


def summarize_by_symbol(rows: list[dict[str, Any]], include_fixed_allowlist: bool) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "gross_win_pct": 0.0,
        "gross_loss_pct": 0.0,
        "total_pnl_pct": 0.0,
        "configs": set(),
        "role": "unknown",
        "sectors": "",
        "is_core_reference": False,
    })
    for row in rows:
        if not include_fixed_allowlist and bool(row.get("fixed_allowlist_config")):
            continue
        symbol = str(row.get("symbol", "")).strip().upper() or "UNKNOWN"
        pnl = to_float(row.get("pnl_pct"))
        rec = agg[symbol]
        rec["trades"] += 1
        rec["configs"].add(str(row.get("config", "")))
        rec["role"] = row.get("role", rec["role"])
        rec["sectors"] = row.get("sectors", rec["sectors"])
        rec["is_core_reference"] = bool(row.get("is_core_reference", rec["is_core_reference"]))
        rec["total_pnl_pct"] += pnl
        if pnl > 0:
            rec["wins"] += 1
            rec["gross_win_pct"] += pnl
        elif pnl < 0:
            rec["losses"] += 1
            rec["gross_loss_pct"] += abs(pnl)
    out: list[dict[str, Any]] = []
    for symbol, rec in agg.items():
        trades = int(rec["trades"])
        wins = int(rec["wins"])
        total = round(float(rec["total_pnl_pct"]), 6)
        avg = round(total / trades, 6) if trades else 0.0
        pf = 99.0 if rec["gross_loss_pct"] == 0 and rec["gross_win_pct"] > 0 else round(rec["gross_win_pct"] / rec["gross_loss_pct"], 6) if rec["gross_loss_pct"] else 0.0
        out.append({
            "symbol": symbol,
            "role": rec["role"],
            "sectors": rec["sectors"],
            "is_core_reference": rec["is_core_reference"],
            "trades": trades,
            "wins": wins,
            "losses": int(rec["losses"]),
            "winrate": round(wins / trades * 100.0, 2) if trades else 0.0,
            "avg_pnl_pct": avg,
            "total_pnl_pct": total,
            "pf": pf,
            "configs_seen": len(rec["configs"]),
            "configs": ";".join(sorted(rec["configs"])),
        })
    return sorted(out, key=lambda r: (r["total_pnl_pct"], r["trades"]), reverse=True)


def summarize_by_config(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"core": 0, "discovery": 0, "unknown": 0, "symbols": set()})
    for row in rows:
        config = str(row.get("config", ""))
        role = str(row.get("role", "unknown")) or "unknown"
        if role not in {"core", "discovery"}:
            role = "unknown"
        agg[config][role] += 1
        agg[config]["symbols"].add(str(row.get("symbol", "")).upper())
    out = []
    for config, rec in agg.items():
        total = int(rec["core"] + rec["discovery"] + rec["unknown"])
        out.append({
            "config": config,
            "total_positions": total,
            "core_positions": rec["core"],
            "discovery_positions": rec["discovery"],
            "unknown_positions": rec["unknown"],
            "discovery_pct": round(rec["discovery"] / total * 100.0, 2) if total else 0.0,
            "unique_symbols": len(rec["symbols"]),
        })
    return sorted(out, key=lambda r: (r["discovery_positions"], r["total_positions"]), reverse=True)


def write_md(path: str | Path, rows_no_fixed: list[dict[str, Any]], rows_all: list[dict[str, Any]], config_rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    strong = [r for r in rows_no_fixed if r["total_pnl_pct"] > 0 and r["trades"] >= 3]
    lines = [
        "# Tagged Universe Selection Summary",
        "",
        "This report shows what symbols the strategy actually selected after adding the tagged discovery universe.",
        "Sector is context only; the strategy rules are not changed by sector tags.",
        "",
        "## Key view: no fixed-allowlist configs",
        "",
    ]
    if not rows_no_fixed:
        lines.append("- No positions found outside fixed-allowlist configs.")
    else:
        lines.append(f"- symbols selected: {len(rows_no_fixed)}")
        lines.append(f"- positive symbols with >=3 trades: {len(strong)}")
    lines.append("")
    lines.append("## Symbols selected by no-allowlist configs")
    lines.append("")
    for row in rows_no_fixed[:40]:
        lines.append(
            f"- **{row['symbol']}**: role={row['role']}, sectors={row['sectors'] or 'untagged'}, "
            f"trades={row['trades']}, winrate={row['winrate']}%, avg={row['avg_pnl_pct']}%, "
            f"total={row['total_pnl_pct']}%, pf={row['pf']}, configs={row['configs_seen']}"
        )
    lines += ["", "## Config selection mix", ""]
    for row in config_rows[:40]:
        lines.append(
            f"- **{row['config']}**: total={row['total_positions']}, core={row['core_positions']}, "
            f"discovery={row['discovery_positions']} ({row['discovery_pct']}%), unique_symbols={row['unique_symbols']}"
        )
    lines += ["", "## Control view: all configs including fixed core", ""]
    for row in rows_all[:20]:
        lines.append(
            f"- **{row['symbol']}**: role={row['role']}, sectors={row['sectors'] or 'untagged'}, "
            f"trades={row['trades']}, total={row['total_pnl_pct']}%, pf={row['pf']}"
        )
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize tagged universe selections by symbol and tag.")
    ap.add_argument("--matrix-root", default="results/tagged_universe_research/matrix")
    ap.add_argument("--layer-json", default="results/strategy_universe_layer/strategy_universe_layer.json")
    ap.add_argument("--out-dir", default="results/tagged_universe_research")
    args = ap.parse_args()

    tags = load_tags(args.layer_json)
    positions = collect_positions(args.matrix_root, tags)
    rows_no_fixed = summarize_by_symbol(positions, include_fixed_allowlist=False)
    rows_all = summarize_by_symbol(positions, include_fixed_allowlist=True)
    config_rows = summarize_by_config(positions)

    out = Path(args.out_dir)
    write_csv(out / "tagged_universe_selection_no_fixed.csv", rows_no_fixed)
    write_csv(out / "tagged_universe_selection_all_configs.csv", rows_all)
    write_csv(out / "tagged_universe_selection_by_config.csv", config_rows)
    write_md(out / "tagged_universe_selection.md", rows_no_fixed, rows_all, config_rows)
    print(out / "tagged_universe_selection.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
