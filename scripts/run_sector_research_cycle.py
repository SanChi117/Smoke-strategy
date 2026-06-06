#!/usr/bin/env python3
"""Run sector-by-sector deep research cycle.

The goal is to avoid overfitting to a fixed hand-picked coin list. This script
runs the same deep research suite over:
- the combined sector universe,
- each sector group separately,
- optional discovery subsets.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_GROUPS_FILE = "strategy_lab/universe/sector_groups.json"


def run_cmd(cmd: list[str], allow_fail: bool = False) -> int:
    print("\n$ " + " ".join(cmd))
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result.returncode


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def read_first_csv(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    with p.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def load_groups(path: str | Path) -> list[str]:
    data = read_json(path)
    return list((data.get("groups") or {}).keys())


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip().lower())


def write_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_universe(groups_file: str, groups: str, top_n: int, exclude: str, out_file: Path, md_out: Path) -> None:
    run_cmd([
        sys.executable,
        "scripts/build_sector_universe.py",
        "--groups-file", groups_file,
        "--groups", groups,
        "--top-n", str(top_n),
        "--exclude", exclude,
        "--out", str(out_file),
        "--md-out", str(md_out),
    ])


def run_deep(symbols_file: Path, out_root: Path, interval: str, limit: int, windows: int, lookback_days: int, profile: str, sleep_sec: float, allow_fail: bool) -> int:
    return run_cmd([
        sys.executable,
        "scripts/run_deep_research_suite.py",
        "--symbols-file", str(symbols_file),
        "--interval", interval,
        "--limit", str(limit),
        "--windows", str(windows),
        "--lookback-days", str(lookback_days),
        "--profile", profile,
        "--root", str(out_root),
        "--sleep-sec", str(sleep_sec),
    ], allow_fail=allow_fail)


def collect_result(label: str, groups: str, run_root: Path, returncode: int) -> dict:
    decision_path = run_root / "decision" / "research_decision.json"
    matrix_path = run_root / "matrix" / "matrix_summary.csv"
    wfo_path = run_root / "walk_forward" / "walk_forward_summary.csv"
    decision = read_json(decision_path)
    matrix_best = decision.get("matrix_best") or read_first_csv(matrix_path)
    wfo = decision.get("walk_forward") or {}
    return {
        "label": label,
        "groups": groups,
        "returncode": returncode,
        "decision": decision.get("decision", "ERROR" if returncode else "UNKNOWN"),
        "best_config": matrix_best.get("name", ""),
        "matrix_ret_pct": matrix_best.get("ret_pct", ""),
        "matrix_pf": matrix_best.get("pf", ""),
        "matrix_dd_pct": matrix_best.get("max_dd_pct", ""),
        "matrix_executed": matrix_best.get("executed_trades", ""),
        "matrix_sanity": matrix_best.get("sanity_status", ""),
        "wfo_valid_folds": wfo.get("valid_folds", ""),
        "wfo_positive_fold_pct": wfo.get("positive_fold_pct", ""),
        "wfo_executed": wfo.get("total_executed_trades", ""),
        "wfo_avg_ret_pct": wfo.get("avg_ret_pct", ""),
        "wfo_avg_pf": wfo.get("avg_pf", ""),
        "wfo_worst_dd_pct": wfo.get("worst_max_dd_pct", ""),
        "run_root": str(run_root),
    }


def write_markdown(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(rows, key=lambda r: float(r.get("wfo_avg_pf") or 0), reverse=True)
    lines = [
        "# Sector Research Cycle Summary",
        "",
        "This is a strategy-first sector rotation research report. It is not live-trading approval.",
        "",
        "## Ranked by WFO average PF",
        "",
    ]
    for row in ranked:
        lines.append(
            f"- **{row.get('label')}**: decision={row.get('decision')}, best={row.get('best_config')}, "
            f"matrix_ret={row.get('matrix_ret_pct')}%, matrix_pf={row.get('matrix_pf')}, "
            f"wfo_pf={row.get('wfo_avg_pf')}, wfo_ret={row.get('wfo_avg_ret_pct')}%, "
            f"wfo_executed={row.get('wfo_executed')}, dd={row.get('wfo_worst_dd_pct')}%, root=`{row.get('run_root')}`"
        )
    lines.extend([
        "",
        "## Notes",
        "- Combined sector universe checks whether strategy logic survives across many narratives.",
        "- Per-sector runs show where capital rotation currently favors or rejects the strategy.",
        "- Discovery runs can block old core coins to test whether new sectors can stand alone.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full sector-by-sector research cycle.")
    parser.add_argument("--groups-file", default=DEFAULT_GROUPS_FILE)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--root", default="results/sector_research_cycle")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    parser.add_argument("--exclude", default="", help="Comma-separated symbols to exclude from every group")
    parser.add_argument("--only", default="", help="Comma-separated group names to run instead of all groups")
    parser.add_argument("--skip-combined", action="store_true")
    parser.add_argument("--allow-fail", action="store_true", help="Continue cycle if one sector run fails")
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    all_groups = load_groups(args.groups_file)
    selected_groups = [part.strip() for part in args.only.split(",") if part.strip()] or all_groups
    rows: list[dict] = []

    print("Smoke Strategy Lab sector research cycle")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print("Order execution: disabled / not implemented")
    print(f"Groups: {len(selected_groups)}")
    print(f"Top N per group: {args.top_n}")

    if not args.skip_combined:
        label = "combined_all_sectors"
        symbols_file = root / label / "symbols.txt"
        md_file = root / label / "sector_universe.md"
        build_universe(args.groups_file, "all" if not args.only else ",".join(selected_groups), args.top_n, args.exclude, symbols_file, md_file)
        run_root = root / label / "deep_research"
        code = run_deep(symbols_file, run_root, args.interval, args.limit, args.windows, args.lookback_days, args.profile, args.sleep_sec, args.allow_fail)
        rows.append(collect_result(label, "all" if not args.only else ",".join(selected_groups), run_root, code))

    for group in selected_groups:
        label = safe_name(group)
        symbols_file = root / label / "symbols.txt"
        md_file = root / label / "sector_universe.md"
        build_universe(args.groups_file, group, args.top_n, args.exclude, symbols_file, md_file)
        run_root = root / label / "deep_research"
        code = run_deep(symbols_file, run_root, args.interval, args.limit, args.windows, args.lookback_days, args.profile, args.sleep_sec, args.allow_fail)
        rows.append(collect_result(label, group, run_root, code))

    write_csv(root / "sector_cycle_summary.csv", rows)
    write_markdown(root / "sector_cycle_summary.md", rows)
    print("\nSector research cycle complete")
    print(root / "sector_cycle_summary.csv")
    print(root / "sector_cycle_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
