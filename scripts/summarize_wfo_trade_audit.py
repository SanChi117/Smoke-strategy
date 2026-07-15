#!/usr/bin/env python3
"""Build robust pooled metrics from strict-OOS portfolio execution audits.

Per-fold PF can be 99 when a fold has no losses. Averaging those values is not a
meaningful strategy statistic. This report pools actual net P&L from every executed
trade across folds and reports transparent counts and concentration diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def read_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                item = dict(row)
                item["audit_file"] = str(path)
                parts = path.parts
                item["fold"] = next((part for part in parts if part.startswith("fold_")), "")
                rows.append(item)
    return rows


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize strict-OOS WFO execution audits")
    parser.add_argument("--root", required=True, help="Long-history result root")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--initial-cash", type=float, default=500.0)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    pattern = f"folds/fold_*/candidates/{args.candidate}/walk_forward_executed_trades.csv"
    paths = sorted(root.glob(pattern))
    rows = read_rows(paths)
    out = Path(args.out_dir) if args.out_dir else root / "trade_audit_summary" / args.candidate
    out.mkdir(parents=True, exist_ok=True)

    pnl = [number(row.get("net_pnl")) for row in rows]
    profits = sum(value for value in pnl if value > 0)
    losses = abs(sum(value for value in pnl if value < 0))
    pooled_pf = profits / losses if losses > 0 else None
    net = sum(pnl)
    folds = sorted({row.get("fold", "") for row in rows if row.get("fold")})
    fold_count = max(len(folds), len(list(root.glob("folds/fold_*"))))
    wins = sum(1 for value in pnl if value > 0)
    losses_count = sum(1 for value in pnl if value < 0)
    flats = len(pnl) - wins - losses_count

    by_symbol: dict[str, float] = defaultdict(float)
    by_setup: dict[str, float] = defaultdict(float)
    by_alignment: dict[str, float] = defaultdict(float)
    by_candle: dict[str, float] = defaultdict(float)
    for row, value in zip(rows, pnl):
        by_symbol[str(row.get("symbol", "unknown"))] += value
        by_setup[str(row.get("setup_type", row.get("kind", "unknown")))] += value
        by_alignment[str(row.get("context_alignment", "unknown"))] += value
        by_candle[str(row.get("candle_type", "unknown"))] += value

    sorted_symbols = sorted(by_symbol.items(), key=lambda item: abs(item[1]), reverse=True)
    absolute_total = sum(abs(value) for value in by_symbol.values())
    top_symbol_share = abs(sorted_symbols[0][1]) / absolute_total * 100.0 if sorted_symbols and absolute_total else 0.0

    summary = {
        "candidate": args.candidate,
        "mode": "POOLED_EXECUTED_STRICT_OOS_TRADES",
        "folds_found": fold_count,
        "executed_trades": len(rows),
        "wins": wins,
        "losses": losses_count,
        "flats": flats,
        "winrate_pct": round(wins / len(rows) * 100.0, 4) if rows else 0.0,
        "gross_profit": round(profits, 8),
        "gross_loss_abs": round(losses, 8),
        "pooled_profit_factor": round(pooled_pf, 6) if pooled_pf is not None else None,
        "net_pnl": round(net, 8),
        "average_return_pct_per_fold": round(net / (args.initial_cash * fold_count) * 100.0, 6) if fold_count else 0.0,
        "average_net_pnl_per_trade": round(net / len(rows), 8) if rows else 0.0,
        "median_r_mult": sorted(number(row.get("r_mult")) for row in rows)[len(rows) // 2] if rows else 0.0,
        "total_fees": round(sum(number(row.get("total_fee")) for row in rows), 8),
        "symbols_traded": len(by_symbol),
        "top_symbol_abs_pnl_share_pct": round(top_symbol_share, 4),
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda item: item[0])),
        "by_setup": dict(sorted(by_setup.items())),
        "by_context_alignment": dict(sorted(by_alignment.items())),
        "by_candle_type": dict(sorted(by_candle.items())),
    }
    (out / "pooled_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out / "executed_trades_all_folds.csv", rows)
    write_csv(out / "symbol_pnl.csv", [{"symbol": key, "net_pnl": value} for key, value in sorted_symbols])

    lines = [
        "# Pooled strict-OOS trade audit",
        "",
        f"- Candidate: **{args.candidate}**",
        f"- Executed trades: **{summary['executed_trades']}**",
        f"- Winrate: **{summary['winrate_pct']}%**",
        f"- Pooled PF: **{summary['pooled_profit_factor']}**",
        f"- Net P&L: **{summary['net_pnl']}**",
        f"- Average return per fold: **{summary['average_return_pct_per_fold']}%**",
        f"- Total fees: **{summary['total_fees']}**",
        f"- Symbols traded: **{summary['symbols_traded']}**",
        f"- Largest symbol share of absolute symbol P&L: **{summary['top_symbol_abs_pnl_share_pct']}%**",
        "",
        "PF is pooled from actual net trade P&L. No 99 sentinel values are averaged.",
    ]
    (out / "pooled_metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((out / "pooled_metrics.md").read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
