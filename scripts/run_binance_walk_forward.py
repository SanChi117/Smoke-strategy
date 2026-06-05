#!/usr/bin/env python3
"""Walk-forward validation for a Smoke Strategy baseline candidate.

This validates one candidate across chronological windows. Each fold includes a
warmup/lookback period before the validation window so rolling symbol selection
has prior trades to learn from.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_research_reports import build_diagnosis  # noqa: E402
from run_binance_real_research import DEFAULT_SYMBOLS, resolve_symbols  # noqa: E402
from strategy_lab.binance_market_data import load_binance_futures_candles
from strategy_lab.config import PipelineConfig
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


DEFAULT_BASELINE = {
    "name": "BASE_T5_C40_FALLBACK",
    "rolling_top_n": 5,
    "min_confidence": 40.0,
    "quality_take_threshold": 65.0,
    "quality_watch_threshold": 50.0,
    "structure_take_threshold": 64.0,
    "structure_watch_threshold": 52.0,
    "allowed_symbols": [],
    "blocked_symbols": [],
    "allowed_setup_types": [],
    "blocked_setup_types": [],
    "allowed_trend_contexts": [],
    "blocked_trend_contexts": [],
    "allowed_volatility_regimes": [],
    "blocked_volatility_regimes": [],
}


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except (TypeError, ValueError):
        return default


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value not in {None, ""} else default))
    except (TypeError, ValueError):
        return default


def to_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(";") if part.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def read_csv_rows(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    p = Path(path)
    with p.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        raise ValueError(f"No candle rows found: {p}")
    if "time" not in fieldnames:
        raise ValueError(f"Candle CSV missing time column: {p}")
    return rows, fieldnames


def write_csv(path: str | Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_baseline(path: str | Path | None) -> dict[str, object]:
    if path is None:
        return dict(DEFAULT_BASELINE)
    p = Path(path)
    if not p.exists():
        print(f"WARNING: baseline not found: {p}; using fallback baseline")
        return dict(DEFAULT_BASELINE)
    data = json.loads(p.read_text(encoding="utf-8"))
    baseline = dict(DEFAULT_BASELINE)
    baseline.update(data)
    return baseline


def baseline_to_cfg(baseline: dict[str, object], name: str, warmup_start: datetime, validation_end: datetime) -> PipelineConfig:
    return replace(
        PipelineConfig(),
        name=name,
        start=warmup_start.date().isoformat(),
        end=(validation_end + timedelta(days=1)).date().isoformat(),
        rolling_top_n=to_int(baseline.get("rolling_top_n"), 5),
        quality_take_threshold=to_float(baseline.get("quality_take_threshold"), 65.0),
        quality_watch_threshold=to_float(baseline.get("quality_watch_threshold"), 50.0),
        structure_take_threshold=to_float(baseline.get("structure_take_threshold"), 64.0),
        structure_watch_threshold=to_float(baseline.get("structure_watch_threshold"), 52.0),
        allowed_symbols=to_tuple(baseline.get("allowed_symbols")),
        blocked_symbols=to_tuple(baseline.get("blocked_symbols")),
        allowed_setup_types=to_tuple(baseline.get("allowed_setup_types")),
        blocked_setup_types=to_tuple(baseline.get("blocked_setup_types")),
        allowed_trend_contexts=to_tuple(baseline.get("allowed_trend_contexts")),
        blocked_trend_contexts=to_tuple(baseline.get("blocked_trend_contexts")),
        allowed_volatility_regimes=to_tuple(baseline.get("allowed_volatility_regimes")),
        blocked_volatility_regimes=to_tuple(baseline.get("blocked_volatility_regimes")),
    )


def make_windows(min_time: datetime, max_time: datetime, lookback_days: int, windows: int) -> list[tuple[datetime, datetime, datetime]]:
    validation_start = min_time + timedelta(days=lookback_days)
    if validation_start >= max_time:
        return []
    windows = max(1, int(windows))
    total_seconds = (max_time - validation_start).total_seconds()
    step_seconds = max(1.0, total_seconds / windows)
    out: list[tuple[datetime, datetime, datetime]] = []
    cur = validation_start
    for idx in range(windows):
        end = max_time if idx == windows - 1 else validation_start + timedelta(seconds=step_seconds * (idx + 1))
        warmup_start = cur - timedelta(days=lookback_days)
        if end > cur:
            out.append((warmup_start, cur, end))
        cur = end
    return out


def row_time(row: dict[str, str]) -> datetime:
    return parse_dt(row["time"])


def filter_rows(rows: list[dict[str, str]], start: datetime, end: datetime) -> list[dict[str, str]]:
    return [row for row in rows if start <= row_time(row) < end]


def score_fold(row: dict[str, object]) -> float:
    if row.get("status") != "OK":
        return -999.0
    executed = to_float(row.get("executed_trades"))
    ret = to_float(row.get("ret_pct"))
    dd = abs(to_float(row.get("max_dd_pct")))
    pf = min(to_float(row.get("pf")), 3.0)
    sanity_penalty = 0.0 if row.get("sanity_status") == "OK" else 10.0
    sparse_penalty = max(0.0, 5.0 - executed) * 2.0
    return round(ret + pf * 2.0 - dd * 0.5 - sanity_penalty - sparse_penalty, 4)


def build_markdown(summary_rows: list[dict[str, object]], baseline: dict[str, object]) -> str:
    ok_rows = [r for r in summary_rows if r.get("status") == "OK"]
    positive_rows = [r for r in ok_rows if to_float(r.get("ret_pct")) > 0]
    sanity_ok_rows = [r for r in ok_rows if r.get("sanity_status") == "OK"]
    total_executed = sum(to_int(r.get("executed_trades")) for r in ok_rows)
    avg_ret = round(mean([to_float(r.get("ret_pct")) for r in ok_rows]), 4) if ok_rows else 0.0
    avg_pf = round(mean([to_float(r.get("pf")) for r in ok_rows]), 4) if ok_rows else 0.0
    worst_dd = round(max([abs(to_float(r.get("max_dd_pct"))) for r in ok_rows], default=0.0), 4)
    positive_pct = round(len(positive_rows) / len(ok_rows) * 100.0, 2) if ok_rows else 0.0
    sanity_ok_pct = round(len(sanity_ok_rows) / len(ok_rows) * 100.0, 2) if ok_rows else 0.0

    if not ok_rows:
        verdict = "BLOCK_NO_VALID_FOLDS"
    elif total_executed < 10:
        verdict = "WATCH_TOO_SPARSE"
    elif positive_pct >= 50 and sanity_ok_pct >= 70 and avg_pf >= 1.0:
        verdict = "PASS_WALK_FORWARD_REVIEW"
    else:
        verdict = "WATCH_UNSTABLE"

    lines = [
        "# Binance Walk-Forward Summary",
        "",
        f"Verdict: **{verdict}**",
        "",
        "## Baseline candidate",
        f"- Name: {baseline.get('name')}",
        f"- Rolling top N: {baseline.get('rolling_top_n')}",
        f"- Min confidence: {baseline.get('min_confidence')}",
        f"- Quality TAKE/WATCH: {baseline.get('quality_take_threshold')} / {baseline.get('quality_watch_threshold')}",
        f"- Structure TAKE/WATCH: {baseline.get('structure_take_threshold')} / {baseline.get('structure_watch_threshold')}",
        f"- Allowed symbols: {', '.join(to_tuple(baseline.get('allowed_symbols'))) or 'none'}",
        f"- Blocked setup types: {', '.join(to_tuple(baseline.get('blocked_setup_types'))) or 'none'}",
        f"- Blocked volatility regimes: {', '.join(to_tuple(baseline.get('blocked_volatility_regimes'))) or 'none'}",
        "",
        "## Aggregate",
        f"- Valid folds: {len(ok_rows)} / {len(summary_rows)}",
        f"- Positive folds: {len(positive_rows)} ({positive_pct}%)",
        f"- Sanity OK folds: {len(sanity_ok_rows)} ({sanity_ok_pct}%)",
        f"- Total executed trades: {total_executed}",
        f"- Average return pct: {avg_ret}%",
        f"- Average PF: {avg_pf}",
        f"- Worst max DD pct: {worst_dd}%",
        "",
        "## Folds",
    ]
    for row in summary_rows:
        lines.append(
            f"- {row.get('fold')}: status={row.get('status')}, score={row.get('score')}, "
            f"ret={row.get('ret_pct')}%, dd={row.get('max_dd_pct')}%, pf={row.get('pf')}, "
            f"executed={row.get('executed_trades')}, sanity={row.get('sanity_status')}, "
            f"window={row.get('validation_start')} -> {row.get('validation_end')}"
        )
        if row.get("error"):
            lines.append(f"  - error: {row.get('error')}")
    lines.extend(["", "## Next step"])
    if verdict == "PASS_WALK_FORWARD_REVIEW":
        lines.append("- Candidate can move to a larger symbol/history run and then paper-mode review.")
    elif verdict == "WATCH_TOO_SPARSE":
        lines.append("- Increase candle limit, symbols, or reduce window count before judging stability.")
    elif verdict == "WATCH_UNSTABLE":
        lines.append("- Compare fold diagnostics and disable weak setup/regime groups before promotion.")
    else:
        lines.append("- Fix data/window generation or baseline configuration before continuing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Binance walk-forward validation for a baseline candidate.")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--symbols-file", default=None)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--candles-out", default="data/binance_walk_forward_candles.csv")
    parser.add_argument("--out-dir", default="results/binance_walk_forward")
    parser.add_argument("--baseline", default="results/binance_real_matrix/baseline_candidate/baseline_candidate.json")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    parser.add_argument("--strict", action="store_true", help="Return non-zero on BLOCK/WATCH verdicts")
    args = parser.parse_args()

    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    symbols = resolve_symbols(args.symbols, args.symbols_file)
    baseline = load_baseline(args.baseline)

    print("Smoke Strategy Lab Binance walk-forward validation")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print(f"Symbols: {len(symbols)}")
    print(f"Interval: {args.interval}")
    print(f"Limit per symbol: {args.limit}")
    print(f"Baseline: {baseline.get('name')}")

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

    rows, fieldnames = read_csv_rows(args.candles_out)
    times = sorted({row_time(row) for row in rows})
    min_time, max_time = times[0], times[-1]
    windows = make_windows(min_time=min_time, max_time=max_time, lookback_days=args.lookback_days, windows=args.windows)

    summary_rows: list[dict[str, object]] = []
    if not windows:
        summary_rows.append({
            "fold": "fold_00",
            "status": "ERROR",
            "error": f"Not enough history for lookback_days={args.lookback_days}. Data: {min_time} -> {max_time}",
        })
    for idx, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold = f"fold_{idx:02d}"
        run_dir = root / fold
        fold_candles = run_dir / "candles.csv"
        fold_rows = filter_rows(rows, warmup_start, validation_end)
        write_csv(fold_candles, fold_rows, fieldnames)
        cfg = baseline_to_cfg(baseline, name=f"WFO_{baseline.get('name')}_{fold}", warmup_start=warmup_start, validation_end=validation_end)
        print(f"\n=== {fold}: {validation_start} -> {validation_end} ({len(fold_rows)} candle rows incl. warmup) ===")
        try:
            summary = run_end_to_end_pipeline(
                candles_csv=fold_candles,
                out_dir=run_dir,
                profile=args.profile,
                min_confidence=to_float(baseline.get("min_confidence"), 40.0),
                cfg=cfg,
            )
            diagnosis, flags = build_diagnosis(run_dir)
            (run_dir / "research_diagnosis.md").write_text(diagnosis, encoding="utf-8")
            row: dict[str, object] = {
                "fold": fold,
                "status": "OK",
                "warmup_start": warmup_start.isoformat(timespec="seconds"),
                "validation_start": validation_start.isoformat(timespec="seconds"),
                "validation_end": validation_end.isoformat(timespec="seconds"),
                "candles": summary.candles,
                "generated_trades": summary.generated_trades,
                "allowed_candidates": summary.allowed_candidates,
                "executed_trades": summary.executed_trades,
                "ret_pct": summary.ret_pct,
                "max_dd_pct": summary.max_dd_pct,
                "pf": summary.pf,
                "winrate": summary.winrate,
                "avg_risk_pct": summary.avg_risk_pct,
                "sanity_status": summary.sanity_status,
                "diagnosis_flags": ";".join(flags),
                "out_dir": str(run_dir),
                "error": "",
            }
            row["score"] = score_fold(row)
            summary_rows.append(row)
            print(f"{fold}: ret={summary.ret_pct}% dd={summary.max_dd_pct}% pf={summary.pf} executed={summary.executed_trades} sanity={summary.sanity_status} score={row['score']}")
        except Exception as exc:  # noqa: BLE001 - continue across research folds
            row = {
                "fold": fold,
                "status": "ERROR",
                "warmup_start": warmup_start.isoformat(timespec="seconds"),
                "validation_start": validation_start.isoformat(timespec="seconds"),
                "validation_end": validation_end.isoformat(timespec="seconds"),
                "candles": len(fold_rows),
                "generated_trades": 0,
                "allowed_candidates": 0,
                "executed_trades": 0,
                "ret_pct": 0.0,
                "max_dd_pct": 0.0,
                "pf": 0.0,
                "winrate": 0.0,
                "avg_risk_pct": 0.0,
                "sanity_status": "ERROR",
                "diagnosis_flags": "FOLD_ERROR",
                "out_dir": str(run_dir),
                "score": -999.0,
                "error": str(exc),
            }
            summary_rows.append(row)
            print(f"{fold}: ERROR {exc}")

    write_csv(root / "walk_forward_summary.csv", summary_rows)
    markdown = build_markdown(summary_rows, baseline)
    (root / "walk_forward_summary.md").write_text(markdown, encoding="utf-8")
    print("\nWalk-forward complete")
    print(root / "walk_forward_summary.csv")
    print(root / "walk_forward_summary.md")
    print("\n" + markdown)

    if args.strict and not markdown.startswith("#"):
        return 1
    if args.strict and "PASS_WALK_FORWARD_REVIEW" not in markdown:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
