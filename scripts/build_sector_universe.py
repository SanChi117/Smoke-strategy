#!/usr/bin/env python3
"""Build a grouped research universe from sector_groups.json.

This creates a comma-separated symbol list for deep research runs.
Research only. No API keys. No exchange/account access. No order execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_GROUPS_PATH = "strategy_lab/universe/sector_groups.json"


def read_groups(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sector groups file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("_", "")


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = normalize_symbol(value)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_symbols(data: dict, selected_groups: list[str], top_n: int, exclude: list[str]) -> list[str]:
    groups = data.get("groups", {})
    if not selected_groups or selected_groups == ["all"]:
        selected_groups = list(groups.keys())
    excluded = {normalize_symbol(item) for item in exclude}
    symbols: list[str] = []
    missing: list[str] = []
    for group in selected_groups:
        if group not in groups:
            missing.append(group)
            continue
        group_symbols = [normalize_symbol(item) for item in groups[group].get("symbols", [])]
        if top_n > 0:
            group_symbols = group_symbols[:top_n]
        symbols.extend([item for item in group_symbols if item not in excluded])
    if missing:
        allowed = ", ".join(sorted(groups.keys()))
        raise ValueError(f"Unknown groups: {missing}. Available groups: {allowed}")
    return unique_keep_order(symbols)


def write_outputs(symbols: list[str], out_file: str | Path | None, md_file: str | Path | None, data: dict, selected_groups: list[str]) -> None:
    if out_file:
        p = Path(out_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(",".join(symbols) + "\n", encoding="utf-8")
    if md_file:
        p = Path(md_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Sector Research Universe",
            "",
            f"Version: `{data.get('version', '')}`",
            f"Selected groups: {', '.join(selected_groups) if selected_groups else 'all'}",
            f"Symbols: {len(symbols)}",
            "",
            "```text",
            ",".join(symbols),
            "```",
            "",
            "## Source policy",
            data.get("source_policy", {}).get("note", "Research seed only."),
            "",
        ]
        p.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build sector/grouped symbol universe for deep research.")
    parser.add_argument("--groups-file", default=DEFAULT_GROUPS_PATH)
    parser.add_argument("--groups", default="all", help="Comma-separated group names or 'all'")
    parser.add_argument("--top-n", type=int, default=10, help="Take top N symbols per group from the seed file")
    parser.add_argument("--exclude", default="", help="Comma-separated symbols to exclude")
    parser.add_argument("--out", default="results/sector_universe/symbols.txt")
    parser.add_argument("--md-out", default="results/sector_universe/sector_universe.md")
    args = parser.parse_args()

    data = read_groups(args.groups_file)
    selected_groups = [part.strip() for part in args.groups.split(",") if part.strip()]
    exclude = [part.strip() for part in args.exclude.split(",") if part.strip()]
    symbols = build_symbols(data=data, selected_groups=selected_groups, top_n=args.top_n, exclude=exclude)
    write_outputs(symbols=symbols, out_file=args.out, md_file=args.md_out, data=data, selected_groups=selected_groups)
    print("Sector universe built")
    print(f"Groups: {', '.join(selected_groups) if selected_groups else 'all'}")
    print(f"Symbols: {len(symbols)}")
    print(",".join(symbols))
    print(args.out)
    print(args.md_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
