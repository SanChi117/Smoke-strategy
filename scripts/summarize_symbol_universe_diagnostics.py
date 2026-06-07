#!/usr/bin/env python3
"""Write compact diagnostics for dynamic symbol-universe research.

The goal is to understand why a broad universe collapses into a tiny set of
tradable symbols without uploading huge per-config CSV artifacts.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
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


def collect_positions(matrix_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    matrix_rows = read_csv(matrix_root / "matrix_summary.csv")
    all_positions: list[dict[str, Any]] = []
    for row in matrix_rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        positions = read_csv(matrix_root / name / "paper" / "paper_positions.csv")
        for pos in positions:
            all_positions.append({**pos, "config": name})
    return all_positions, matrix_rows


def summarize_by_symbol(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "flat": 0,
        "gross_win_pct": 0.0,
        "gross_loss_pct": 0.0,
        "total_pnl_pct": 0.0,
        "configs": set(),
        "setup_types": defaultdict(int),
        "close_reasons": defaultdict(int),
    })
    for pos in positions:
        symbol = str(pos.get("symbol", "")).strip().upper() or "UNKNOWN"
        pnl = to_float(pos.get("pnl_pct"))
        rec = agg[symbol]
        rec["trades"] += 1
        rec["configs"].add(str(pos.get("config", "")))
        rec["total_pnl_pct"] += pnl
        if pnl > 0:
            rec["wins"] += 1
            rec["gross_win_pct"] += pnl
        elif pnl < 0:
            rec["losses"] += 1
            rec["gross_loss_pct"] += abs(pnl)
        else:
            rec["flat"] += 1
        setup = str(pos.get("setup_type", "")).strip() or "unknown"
        reason = str(pos.get("close_reason", "")).strip() or "unknown"
        rec["setup_types"][setup] += 1
        rec["close_reasons"][reason] += 1

    rows: list[dict[str, Any]] = []
    for symbol, rec in agg.items():
        trades = int(rec["trades"])
        wins = int(rec["wins"])
        total = round(float(rec["total_pnl_pct"]), 6)
        avg = round(total / trades, 6) if trades else 0.0
        pf = 99.0 if rec["gross_loss_pct"] == 0 and rec["gross_win_pct"] > 0 else round(rec["gross_win_pct"] / rec["gross_loss_pct"], 6) if rec["gross_loss_pct"] else 0.0
        rows.append({
            "symbol": symbol,
            "trades": trades,
            "wins": wins,
            "losses": int(rec["losses"]),
            "winrate": round(wins / trades * 100.0, 2) if trades else 0.0,
            "avg_pnl_pct": avg,
            "total_pnl_pct": total,
            "pf": pf,
            "configs_seen": len(rec["configs"]),
            "top_setup_types": ";".join(f"{k}:{v}" for k, v in sorted(rec["setup_types"].items(), key=lambda kv: kv[1], reverse=True)[:5]),
            "close_reasons": ";".join(f"{k}:{v}" for k, v in sorted(rec["close_reasons"].items(), key=lambda kv: kv[1], reverse=True)[:5]),
        })
    return sorted(rows, key=lambda r: (r["total_pnl_pct"], r["trades"]), reverse=True)


def summarize_configs(matrix_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in matrix_rows:
        generated = to_float(row.get("generated_trades"))
        allowed = to_float(row.get("allowed_candidates"))
        out.append({
            "name": row.get("name", ""),
            "score": to_float(row.get("score")),
            "ret_pct": to_float(row.get("ret_pct")),
            "max_dd_pct": to_float(row.get("max_dd_pct")),
            "pf": to_float(row.get("pf")),
            "winrate": to_float(row.get("winrate")),
            "executed_trades": int(to_float(row.get("executed_trades"))),
            "allowed_candidates": int(allowed),
            "generated_trades": int(generated),
            "allowed_pct": round(allowed / generated * 100.0, 4) if generated else 0.0,
            "sanity_status": row.get("sanity_status", ""),
            "diagnosis_flags": row.get("diagnosis_flags", ""),
        })
    return sorted(out, key=lambda r: (r["ret_pct"], r["pf"], r["executed_trades"]), reverse=True)


def write_md(path: str | Path, symbol_rows: list[dict[str, Any]], config_rows: list[dict[str, Any]], positions_count: int) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Symbol Universe Diagnostics",
        "",
        "Compact diagnostic report. Sector remains context only; this report explains filter behavior.",
        "",
        f"- paper positions scanned: {positions_count}",
        f"- symbols with paper positions: {len(symbol_rows)}",
        f"- configs scanned: {len(config_rows)}",
        "",
        "## Main finding",
        "",
    ]
    if len(symbol_rows) <= 1:
        lines.append("- The current dynamic pipeline is collapsing into one or almost one symbol. This means the gate stack is too narrow for a broad flexible universe.")
    else:
        lines.append("- Multiple symbols passed the dynamic pipeline. Rank by stability before promotion.")
    lines.append("")

    lines += ["## Symbols by total PnL", ""]
    for row in symbol_rows[:25]:
        lines.append(
            f"- **{row['symbol']}**: trades={row['trades']}, winrate={row['winrate']}%, "
            f"avg={row['avg_pnl_pct']}%, total={row['total_pnl_pct']}%, pf={row['pf']}, "
            f"setups={row['top_setup_types']}, closes={row['close_reasons']}"
        )
    lines.append("")

    lines += ["## Configs by return", ""]
    for row in config_rows[:25]:
        lines.append(
            f"- **{row['name']}**: ret={row['ret_pct']}%, pf={row['pf']}, dd={row['max_dd_pct']}%, "
            f"executed={row['executed_trades']}, allowed={row['allowed_pct']}%, sanity={row['sanity_status']}, flags={row['diagnosis_flags']}"
        )
    lines.append("")

    lines += ["## Next tuning direction", ""]
    lines.append("- Do not promote the dynamic baseline while WFO folds are negative.")
    lines.append("- Keep BCHUSDT as a candidate to validate, not as a hardcoded universe.")
    lines.append("- Add a tuning cycle that compares looser universe gates against setup/regime blocks, then re-run WFO.")
    p.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize dynamic symbol-universe diagnostics.")
    ap.add_argument("--matrix-root", default="results/symbol_universe_research/deep_research/matrix")
    ap.add_argument("--out-dir", default="results/symbol_universe_research")
    args = ap.parse_args()

    matrix_root = Path(args.matrix_root)
    out = Path(args.out_dir)
    positions, matrix_rows = collect_positions(matrix_root)
    symbol_rows = summarize_by_symbol(positions)
    config_rows = summarize_configs(matrix_rows)

    write_csv(out / "symbol_universe_diagnostics_by_symbol.csv", symbol_rows)
    write_csv(out / "symbol_universe_diagnostics_by_config.csv", config_rows)
    write_md(out / "symbol_universe_diagnostics.md", symbol_rows, config_rows, len(positions))

    print(out / "symbol_universe_diagnostics.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
