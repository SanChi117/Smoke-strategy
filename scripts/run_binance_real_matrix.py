#!/usr/bin/env python3
"""Run a compact parameter matrix on real Binance public candles.

The matrix reuses one downloaded candles file, then compares several research
configurations. It is meant to answer: are we too strict, too loose, or too sparse?

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, replace
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_research_reports import build_diagnosis  # noqa: E402
from promote_matrix_baseline import normalize_row, write_markdown  # noqa: E402
from run_binance_real_research import DEFAULT_SYMBOLS, resolve_symbols  # noqa: E402
from strategy_lab.binance_market_data import load_binance_futures_candles
from strategy_lab.config import PipelineConfig
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


MATRIX_CONFIGS = [
    {
        "name": "BASE_T5_C40",
        "rolling_top_n": 5,
        "min_confidence": 40.0,
        "quality_take_threshold": 65.0,
        "quality_watch_threshold": 50.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 52.0,
    },
    {
        "name": "MORE_COINS_T8_C40",
        "rolling_top_n": 8,
        "min_confidence": 40.0,
        "quality_take_threshold": 65.0,
        "quality_watch_threshold": 50.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 52.0,
    },
    {
        "name": "MORE_COINS_T10_C35",
        "rolling_top_n": 10,
        "min_confidence": 35.0,
        "quality_take_threshold": 65.0,
        "quality_watch_threshold": 50.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 52.0,
    },
    {
        "name": "SOFTER_GATES_T8_C35",
        "rolling_top_n": 8,
        "min_confidence": 35.0,
        "quality_take_threshold": 60.0,
        "quality_watch_threshold": 45.0,
        "structure_take_threshold": 60.0,
        "structure_watch_threshold": 48.0,
    },
    {
        "name": "STRICT_T5_C50",
        "rolling_top_n": 5,
        "min_confidence": 50.0,
        "quality_take_threshold": 70.0,
        "quality_watch_threshold": 55.0,
        "structure_take_threshold": 68.0,
        "structure_watch_threshold": 56.0,
    },
]


def write_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_baseline_candidate(root: Path, rows: list[dict]) -> None:
    if not rows:
        return
    baseline_dir = root / "baseline_candidate"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    candidate = normalize_row({key: str(value) for key, value in rows[0].items()})
    candidate["source_matrix"] = str(root / "matrix_summary.csv")
    import json
    (baseline_dir / "baseline_candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(baseline_dir / "baseline_candidate.md", candidate, [{key: str(value) for key, value in row.items()} for row in rows])


def score_row(row: dict) -> float:
    executed = float(row.get("executed_trades", 0) or 0)
    ret = float(row.get("ret_pct", 0) or 0)
    dd = abs(float(row.get("max_dd_pct", 0) or 0))
    pf = float(row.get("pf", 0) or 0)
    allowed_pct = float(row.get("allowed_pct", 0) or 0)
    sanity_penalty = 20.0 if row.get("sanity_status") == "FAIL" else 8.0 if row.get("sanity_status") == "WARN" else 0.0
    sparse_penalty = max(0.0, 10.0 - executed) * 2.0
    return round(ret + (pf * 3.0) + min(allowed_pct, 25.0) * 0.2 - dd * 0.5 - sanity_penalty - sparse_penalty, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Binance real-data research matrix.")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS, help="Comma/newline separated symbols")
    parser.add_argument("--symbols-file", default=None, help="Text file with comma/newline separated symbols")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--candles-out", default="data/binance_real_matrix_candles.csv")
    parser.add_argument("--out-dir", default="results/binance_real_matrix")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    args = parser.parse_args()

    symbols = resolve_symbols(args.symbols, args.symbols_file)
    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)

    print("Smoke Strategy Lab Binance real matrix")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print(f"Symbols: {len(symbols)}")
    print(f"Interval: {args.interval}")
    print(f"Limit per symbol: {args.limit}")

    market_summary = load_binance_futures_candles(
        symbols=symbols,
        out_csv=args.candles_out,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    print("Market data summary")
    for key, value in asdict(market_summary).items():
        print(f"{key}: {value}")
    if market_summary.status != "OK":
        return 1

    rows: list[dict] = []
    for cfg_spec in MATRIX_CONFIGS:
        name = cfg_spec["name"]
        run_dir = root / name
        cfg = replace(
            PipelineConfig(),
            name=name,
            rolling_top_n=int(cfg_spec["rolling_top_n"]),
            quality_take_threshold=float(cfg_spec["quality_take_threshold"]),
            quality_watch_threshold=float(cfg_spec["quality_watch_threshold"]),
            structure_take_threshold=float(cfg_spec["structure_take_threshold"]),
            structure_watch_threshold=float(cfg_spec["structure_watch_threshold"]),
        )
        print(f"\n=== Running {name} ===")
        summary = run_end_to_end_pipeline(
            candles_csv=args.candles_out,
            out_dir=run_dir,
            profile=args.profile,
            min_confidence=float(cfg_spec["min_confidence"]),
        )
        diagnosis, flags = build_diagnosis(run_dir)
        (run_dir / "research_diagnosis.md").write_text(diagnosis, encoding="utf-8")
        generated = int(summary.generated_trades)
        allowed = int(summary.allowed_candidates)
        row = {
            "name": name,
            "rolling_top_n": cfg.rolling_top_n,
            "min_confidence": cfg_spec["min_confidence"],
            "quality_take_threshold": cfg.quality_take_threshold,
            "quality_watch_threshold": cfg.quality_watch_threshold,
            "structure_take_threshold": cfg.structure_take_threshold,
            "structure_watch_threshold": cfg.structure_watch_threshold,
            "generated_trades": generated,
            "allowed_candidates": allowed,
            "allowed_pct": round(allowed / generated * 100.0, 2) if generated else 0.0,
            "executed_trades": summary.executed_trades,
            "ret_pct": summary.ret_pct,
            "max_dd_pct": summary.max_dd_pct,
            "pf": summary.pf,
            "winrate": summary.winrate,
            "avg_risk_pct": summary.avg_risk_pct,
            "sanity_status": summary.sanity_status,
            "diagnosis_flags": ";".join(flags),
            "out_dir": str(run_dir),
        }
        row["score"] = score_row(row)
        rows.append(row)
        print(f"{name}: ret={summary.ret_pct}% dd={summary.max_dd_pct}% pf={summary.pf} executed={summary.executed_trades} sanity={summary.sanity_status} score={row['score']}")

    rows = sorted(rows, key=lambda item: float(item["score"]), reverse=True)
    write_csv(root / "matrix_summary.csv", rows)
    write_baseline_candidate(root, rows)

    best = rows[0] if rows else {}
    lines = [
        "# Binance Real Matrix Summary",
        "",
        f"Best config: **{best.get('name', 'none')}**",
        f"Score: {best.get('score', '')}",
        f"Return: {best.get('ret_pct', '')}%",
        f"Max DD: {best.get('max_dd_pct', '')}%",
        f"PF: {best.get('pf', '')}",
        f"Executed trades: {best.get('executed_trades', '')}",
        f"Sanity: {best.get('sanity_status', '')}",
        "",
        "## All configs",
    ]
    for row in rows:
        lines.append(
            f"- {row['name']}: score={row['score']}, ret={row['ret_pct']}%, dd={row['max_dd_pct']}%, "
            f"pf={row['pf']}, executed={row['executed_trades']}, allowed={row['allowed_pct']}%, sanity={row['sanity_status']}"
        )
    lines.append("")
    lines.append("## Next step")
    if best and float(best.get("executed_trades", 0) or 0) < 10:
        lines.append("- Increase symbols/history before judging the strategy; best config is still too sparse.")
    elif best and best.get("sanity_status") != "OK":
        lines.append("- Inspect best config diagnosis warnings before changing strategy defaults.")
    else:
        lines.append("- Promote the best config to a candidate baseline and run walk-forward validation.")
    (root / "matrix_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nMatrix complete")
    print(root / "matrix_summary.csv")
    print(root / "matrix_summary.md")
    print(root / "baseline_candidate" / "baseline_candidate.md")
    print(root / "baseline_candidate" / "baseline_candidate.json")
    print("\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
