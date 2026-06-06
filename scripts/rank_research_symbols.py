#!/usr/bin/env python3
"""Rank tradable symbols across the whole research universe.

Sectors are used only as metadata/context. This script does not select or block
entire sectors. It scans paper positions produced by matrix research configs and
builds a coin-first ranking with sector labels attached for analysis.

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
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_sector_map(groups_file: str | Path) -> dict[str, list[str]]:
    p = Path(groups_file)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = defaultdict(list)
    for group, payload in (data.get("groups") or {}).items():
        if isinstance(payload, dict):
            symbols = payload.get("symbols") or []
        else:
            symbols = payload or []
        for symbol in symbols:
            s = str(symbol).strip().upper()
            if s and group not in result[s]:
                result[s].append(group)
    return dict(result)


def read_matrix_config_meta(matrix_root: str | Path) -> dict[str, dict[str, str]]:
    rows = read_csv(Path(matrix_root) / "matrix_summary.csv")
    return {str(row.get("name", "")).strip(): row for row in rows if str(row.get("name", "")).strip()}


def has_fixed_allowlist(row: dict[str, str] | None) -> bool:
    if not row:
        return False
    return bool(str(row.get("allowed_symbols_filter", "")).strip())


def list_config_dirs(matrix_root: str | Path, include_fixed_allowlist: bool) -> list[Path]:
    root = Path(matrix_root)
    if not root.exists():
        return []
    meta = read_matrix_config_meta(root)
    result: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or not (p / "paper" / "paper_positions.csv").exists():
            continue
        if not include_fixed_allowlist and has_fixed_allowlist(meta.get(p.name)):
            continue
        result.append(p)
    return result


def symbol_bucket(trades: int, winrate: float, avg_pnl: float, pf: float) -> str:
    if trades >= 8 and avg_pnl > 0 and pf >= 1.4 and winrate >= 50:
        return "STRONG"
    if trades >= 3 and avg_pnl > 0 and pf >= 1.0:
        return "WATCH"
    if trades > 0 and avg_pnl > 0:
        return "WATCH"
    return "BLOCK"


def score_symbol(trades: int, avg_pnl: float, total_pnl: float, pf: float, winrate: float, configs: int) -> float:
    capped_pf = min(pf, 5.0)
    return round(avg_pnl * 3.0 + total_pnl * 0.15 + capped_pf * 1.5 + winrate * 0.02 + min(trades, 30) * 0.1 + configs * 0.25, 6)


def aggregate_symbols(matrix_root: str | Path, sector_map: dict[str, list[str]], include_fixed_allowlist: bool) -> tuple[list[dict[str, Any]], list[str]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    used_configs: list[str] = []

    for cfg_dir in list_config_dirs(matrix_root, include_fixed_allowlist=include_fixed_allowlist):
        cfg_name = cfg_dir.name
        used_configs.append(cfg_name)
        rows = read_csv(cfg_dir / "paper" / "paper_positions.csv")
        for row in rows:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            pnl = to_float(row.get("pnl_pct"))
            rec = by_symbol.setdefault(symbol, {
                "symbol": symbol,
                "sectors": ";".join(sector_map.get(symbol, [])),
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "gross_win_pct": 0.0,
                "gross_loss_pct": 0.0,
                "total_pnl_pct": 0.0,
                "configs": set(),
                "best_config": "",
                "best_config_avg_pnl_pct": -999999.0,
                "config_pnls": defaultdict(list),
            })
            rec["trades"] += 1
            rec["configs"].add(cfg_name)
            rec["total_pnl_pct"] += pnl
            rec["config_pnls"][cfg_name].append(pnl)
            if pnl > 0:
                rec["wins"] += 1
                rec["gross_win_pct"] += pnl
            elif pnl < 0:
                rec["losses"] += 1
                rec["gross_loss_pct"] += abs(pnl)

    out: list[dict[str, Any]] = []
    for symbol, rec in by_symbol.items():
        trades = int(rec["trades"])
        wins = int(rec["wins"])
        losses = int(rec["losses"])
        total = round(float(rec["total_pnl_pct"]), 6)
        avg = round(total / trades, 6) if trades else 0.0
        winrate = round(wins / trades * 100.0, 2) if trades else 0.0
        pf = 99.0 if rec["gross_loss_pct"] == 0 and rec["gross_win_pct"] > 0 else round(rec["gross_win_pct"] / rec["gross_loss_pct"], 6) if rec["gross_loss_pct"] else 0.0

        best_config = ""
        best_avg = -999999.0
        for cfg_name, pnls in rec["config_pnls"].items():
            if not pnls:
                continue
            cfg_avg = sum(pnls) / len(pnls)
            if cfg_avg > best_avg:
                best_avg = cfg_avg
                best_config = cfg_name

        bucket = symbol_bucket(trades, winrate, avg, pf)
        out.append({
            "symbol": symbol,
            "bucket": bucket,
            "score": score_symbol(trades, avg, total, pf, winrate, len(rec["configs"])),
            "sectors": rec["sectors"],
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "avg_pnl_pct": avg,
            "total_pnl_pct": total,
            "pf": pf,
            "configs_seen": len(rec["configs"]),
            "best_config": best_config,
            "best_config_avg_pnl_pct": round(best_avg, 6) if best_config else 0.0,
        })

    rows = sorted(out, key=lambda r: (r["bucket"] == "STRONG", r["score"], r["trades"]), reverse=True)
    return rows, used_configs


def write_markdown(path: str | Path, rows: list[dict[str, Any]], top_n: int, used_configs: list[str], include_fixed_allowlist: bool) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Symbol Research Ranking",
        "",
        "Coin-first report. Sector is context only, not a trading boundary.",
        f"Fixed allowlist configs included: `{include_fixed_allowlist}`",
        f"Configs used: {len(used_configs)}",
        "",
    ]
    for bucket in ["STRONG", "WATCH", "BLOCK"]:
        part = [r for r in rows if r["bucket"] == bucket]
        lines += [f"## {bucket} symbols", ""]
        if not part:
            lines += ["- none", ""]
            continue
        for r in part[:top_n if bucket != "BLOCK" else min(top_n, 25)]:
            lines.append(
                f"- **{r['symbol']}**: score={r['score']}, sectors={r['sectors'] or 'unknown'}, "
                f"trades={r['trades']}, winrate={r['winrate']}%, avg_pnl={r['avg_pnl_pct']}%, "
                f"total_pnl={r['total_pnl_pct']}%, pf={r['pf']}, best_config={r['best_config']}"
            )
        lines.append("")
    lines += ["## Configs used", ""]
    for cfg in used_configs:
        lines.append(f"- {cfg}")
    p.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank symbols across research configs with sector labels as context.")
    ap.add_argument("--matrix-root", default="results/sector_research_cycle/combined_all_sectors/deep_research/matrix")
    ap.add_argument("--groups-file", default="strategy_lab/universe/sector_groups.json")
    ap.add_argument("--out-dir", default="results/sector_research_cycle")
    ap.add_argument("--top-n", type=int, default=25)
    ap.add_argument("--include-fixed-allowlist", action="store_true", help="Include old fixed-core allowlist configs in symbol ranking. Default: exclude them.")
    args = ap.parse_args()

    sector_map = load_sector_map(args.groups_file)
    rows, used_configs = aggregate_symbols(args.matrix_root, sector_map, include_fixed_allowlist=args.include_fixed_allowlist)
    out = Path(args.out_dir)
    write_csv(out / "symbol_research_ranking.csv", rows)
    write_markdown(out / "symbol_research_ranking.md", rows, args.top_n, used_configs, args.include_fixed_allowlist)

    candidate = {
        "name": "DYNAMIC_SYMBOL_UNIVERSE_WITH_SECTOR_CONTEXT",
        "status": "research_candidate_only",
        "selection_logic": "rank symbols across the full universe; sector is context only",
        "fixed_allowlist_configs_included": args.include_fixed_allowlist,
        "configs_used": used_configs,
        "strong_symbols": [r["symbol"] for r in rows if r["bucket"] == "STRONG"],
        "watch_symbols": [r["symbol"] for r in rows if r["bucket"] == "WATCH"],
        "sector_usage": "metadata/context, not a hard allowlist or blocklist",
        "source_matrix_root": str(args.matrix_root),
    }
    (out / "dynamic_symbol_universe_candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")

    print(out / "symbol_research_ranking.md")
    print(out / "dynamic_symbol_universe_candidate.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
