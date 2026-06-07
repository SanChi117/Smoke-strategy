#!/usr/bin/env python3
"""Build a strategy universe layer without changing the strategy.

Purpose:
- keep the proven/reference strategy baseline separate from universe management;
- keep core symbols as the control set;
- add a discovery pool from sector_groups.json;
- attach sector tags to symbols for reporting;
- do not promote sectors to trading rules;
- do not run backtests, paper mode, live mode, or orders.

This is a lightweight metadata/universe layer.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_GROUPS_FILE = "strategy_lab/universe/sector_groups.json"
DEFAULT_CORE = "INJUSDT,TONUSDT,DOGEUSDT,ARBUSDT,NEARUSDT,OPUSDT"


def normalize_symbol(value: str) -> str:
    return str(value).strip().upper().replace("/", "").replace("_", "")


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        symbol = normalize_symbol(value)
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def parse_symbols(value: str) -> list[str]:
    return unique_keep_order([part.strip() for part in str(value).replace("\n", ",").split(",") if part.strip()])


def build_sector_tags(data: dict[str, Any], top_n_per_group: int) -> dict[str, dict[str, Any]]:
    tags: dict[str, dict[str, Any]] = {}
    groups = data.get("groups", {}) or {}
    for group_name, group_payload in groups.items():
        if not isinstance(group_payload, dict):
            symbols = list(group_payload or [])
            description = ""
        else:
            symbols = list(group_payload.get("symbols") or [])
            description = str(group_payload.get("description", ""))
        if top_n_per_group > 0:
            symbols = symbols[:top_n_per_group]
        for rank, raw_symbol in enumerate(symbols, start=1):
            symbol = normalize_symbol(raw_symbol)
            if not symbol:
                continue
            rec = tags.setdefault(symbol, {
                "symbol": symbol,
                "sectors": [],
                "sector_rankings": {},
                "sector_descriptions": {},
            })
            if group_name not in rec["sectors"]:
                rec["sectors"].append(group_name)
            rec["sector_rankings"][group_name] = rank
            rec["sector_descriptions"][group_name] = description
    return tags


def build_layer(data: dict[str, Any], core_symbols: list[str], top_n_per_group: int, extra_symbols: list[str], exclude_symbols: list[str]) -> dict[str, Any]:
    exclude = set(exclude_symbols)
    tags = build_sector_tags(data, top_n_per_group=top_n_per_group)
    discovery_symbols = unique_keep_order(list(tags.keys()) + extra_symbols)
    discovery_symbols = [s for s in discovery_symbols if s not in exclude]
    core_symbols = [s for s in core_symbols if s not in exclude]
    combined_symbols = unique_keep_order(core_symbols + discovery_symbols)

    symbol_rows: list[dict[str, Any]] = []
    for symbol in combined_symbols:
        rec = tags.get(symbol, {"sectors": [], "sector_rankings": {}, "sector_descriptions": {}})
        symbol_rows.append({
            "symbol": symbol,
            "role": "core" if symbol in core_symbols else "discovery",
            "sectors": rec.get("sectors", []),
            "sector_rankings": rec.get("sector_rankings", {}),
            "is_core_reference": symbol in core_symbols,
        })

    sector_counts: dict[str, int] = defaultdict(int)
    for row in symbol_rows:
        for sector in row["sectors"]:
            sector_counts[sector] += 1

    return {
        "version": "strategy_universe_layer_v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "metadata_layer_only",
        "strategy_policy": {
            "strategy_changed": False,
            "sector_is_trading_rule": False,
            "sector_is_context_tag": True,
            "live_trading": False,
            "order_execution": False,
            "note": "This layer only prepares symbols and tags. It must not replace the proven strategy baseline.",
        },
        "source": {
            "groups_version": data.get("version", ""),
            "groups_status": data.get("status", ""),
            "top_n_per_group": top_n_per_group,
        },
        "core_reference_symbols": core_symbols,
        "discovery_symbols": [s for s in discovery_symbols if s not in core_symbols],
        "combined_symbols": combined_symbols,
        "symbols": symbol_rows,
        "sector_counts": dict(sorted(sector_counts.items())),
    }


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "role", "sectors", "is_core_reference", "sector_rankings"]
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "symbol": row["symbol"],
                "role": row["role"],
                "sectors": ";".join(row.get("sectors") or []),
                "is_core_reference": row.get("is_core_reference", False),
                "sector_rankings": json.dumps(row.get("sector_rankings", {}), ensure_ascii=False),
            })


def write_txt(path: str | Path, symbols: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(",".join(symbols) + "\n", encoding="utf-8")


def write_md(path: str | Path, layer: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Strategy Universe Layer",
        "",
        "This is a metadata/universe layer only. It does not change the strategy, baseline, filters, risk logic, paper mode, or execution.",
        "",
        "## Policy",
        "",
        "- Strategy changed: `False`",
        "- Sector is trading rule: `False`",
        "- Sector is context tag: `True`",
        "- Live trading: `False`",
        "- Order execution: `False`",
        "",
        "## Core reference symbols",
        "",
        ", ".join(layer["core_reference_symbols"]) or "none",
        "",
        "## Combined universe",
        "",
        f"- total symbols: {len(layer['combined_symbols'])}",
        f"- discovery symbols: {len(layer['discovery_symbols'])}",
        "",
        "```text",
        ",".join(layer["combined_symbols"]),
        "```",
        "",
        "## Sector counts as tags",
        "",
    ]
    for sector, count in layer["sector_counts"].items():
        lines.append(f"- {sector}: {count}")
    lines += ["", "## Symbols", ""]
    for row in layer["symbols"]:
        sectors = ", ".join(row.get("sectors") or []) or "untagged"
        lines.append(f"- **{row['symbol']}**: role={row['role']}, sectors={sectors}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strategy universe layer with sector tags.")
    parser.add_argument("--groups-file", default=DEFAULT_GROUPS_FILE)
    parser.add_argument("--core-symbols", default=DEFAULT_CORE)
    parser.add_argument("--top-n-per-group", type=int, default=10)
    parser.add_argument("--extra-symbols", default="", help="Comma-separated extra discovery symbols")
    parser.add_argument("--exclude-symbols", default="", help="Comma-separated symbols to exclude")
    parser.add_argument("--out-dir", default="results/strategy_universe_layer")
    args = parser.parse_args()

    data = read_json(args.groups_file)
    core_symbols = parse_symbols(args.core_symbols)
    extra_symbols = parse_symbols(args.extra_symbols)
    exclude_symbols = parse_symbols(args.exclude_symbols)
    layer = build_layer(
        data=data,
        core_symbols=core_symbols,
        top_n_per_group=args.top_n_per_group,
        extra_symbols=extra_symbols,
        exclude_symbols=exclude_symbols,
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "strategy_universe_layer.json").write_text(json.dumps(layer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out / "strategy_universe_tags.csv", layer["symbols"])
    write_txt(out / "combined_symbols.txt", layer["combined_symbols"])
    write_txt(out / "core_reference_symbols.txt", layer["core_reference_symbols"])
    write_txt(out / "discovery_symbols.txt", layer["discovery_symbols"])
    write_md(out / "strategy_universe_layer.md", layer)

    print("Strategy universe layer built")
    print(out / "strategy_universe_layer.md")
    print(out / "strategy_universe_layer.json")
    print(out / "combined_symbols.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
