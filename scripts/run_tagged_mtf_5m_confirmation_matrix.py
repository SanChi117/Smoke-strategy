#!/usr/bin/env python3
"""Tagged MTF 5m micro-confirmation matrix.

Research-only A/B test:
- 5m raw candles are downloaded as public market data;
- 15m entry candles are rebuilt from 5m candles;
- 5m micro context is attached to each generated 15m setup;
- baseline is compared with micro-confirmation variants.

No API keys, no private data, no order execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_research_reports import build_diagnosis  # noqa: E402
from promote_matrix_baseline import normalize_row, write_markdown  # noqa: E402
from run_binance_real_matrix import score_row, sort_key  # noqa: E402
from run_binance_real_research import DEFAULT_SYMBOLS, resolve_symbols  # noqa: E402
from strategy_lab.binance_market_data import load_binance_futures_candles  # noqa: E402
from strategy_lab.candle_pipeline import run_candle_pipeline  # noqa: E402
from strategy_lab.config import PipelineConfig  # noqa: E402
from strategy_lab.end_to_end_pipeline import write_pipeline_allowed_trades  # noqa: E402
from strategy_lab.market_data import Candle, group_candles_by_symbol, read_candles_csv, write_candles_csv  # noqa: E402
from strategy_lab.mtf_feature_builder import build_basic_context, latest_context  # noqa: E402
from strategy_lab.paper_mode import run_paper_mode  # noqa: E402
from strategy_lab.pipeline import run_pipeline  # noqa: E402
from strategy_lab.report_sanity import write_report_sanity  # noqa: E402


FILTER_KEYS = [
    "allowed_symbols",
    "blocked_symbols",
    "allowed_setup_types",
    "blocked_setup_types",
    "allowed_trend_contexts",
    "blocked_trend_contexts",
    "allowed_volatility_regimes",
    "blocked_volatility_regimes",
    "allowed_liquidity_states",
    "blocked_liquidity_states",
    "allowed_candle_types",
    "blocked_candle_types",
    "allowed_direction_contexts",
    "blocked_direction_contexts",
]


def hybrid_base(name: str, **overrides: object) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "name": name,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 43.0,
        "quality_take_threshold": 66.0,
        "quality_watch_threshold": 54.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 54.0,
        "min_volume_ratio": 0.70,
        "allowed_setup_types": ("pullback", "ignition"),
        "allowed_direction_contexts": ("down",),
        "blocked_setup_types": ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        "blocked_trend_contexts": (),
        "blocked_volatility_regimes": ("high",),
        "blocked_liquidity_states": ("high_sweep_reject",),
        "blocked_candle_types": ("bear_rejection",),
        "allowed_micro_confirm_states": (),
        "blocked_micro_confirm_states": (),
    }
    cfg.update(overrides)
    return cfg


MICRO_CONFIGS = [
    hybrid_base("TAGGED_MTF_15M_HYBRID_BASELINE"),
    hybrid_base("TAGGED_MTF_5M_CONFIRM_STRICT", allowed_micro_confirm_states=("confirmed",)),
    hybrid_base("TAGGED_MTF_5M_CONFIRM_NEUTRAL_OK", allowed_micro_confirm_states=("confirmed", "neutral")),
    hybrid_base("TAGGED_MTF_5M_CONFIRM_BLOCK_REJECT", blocked_micro_confirm_states=("rejected",)),
]


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("Z", "").replace("T", " "))


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


def bucket_15m(time: datetime) -> datetime:
    return time.replace(minute=(time.minute // 15) * 15, second=0, microsecond=0)


def resample_5m_to_15m(rows: list[Candle]) -> list[Candle]:
    out: list[Candle] = []
    for symbol, symbol_rows in group_candles_by_symbol(rows).items():
        buckets: dict[datetime, list[Candle]] = {}
        for candle in sorted(symbol_rows, key=lambda c: c.time):
            buckets.setdefault(bucket_15m(candle.time), []).append(candle)
        for bucket_rows in buckets.values():
            if len(bucket_rows) < 3:
                continue
            bucket_rows = sorted(bucket_rows, key=lambda c: c.time)
            first = bucket_rows[0]
            last = bucket_rows[-1]
            out.append(Candle(
                symbol=symbol,
                time=last.time,
                open=first.open,
                high=max(c.high for c in bucket_rows),
                low=min(c.low for c in bucket_rows),
                close=last.close,
                volume=sum(c.volume for c in bucket_rows),
            ))
    return sorted(out, key=lambda c: (c.symbol, c.time))


def build_micro_context(raw_5m: list[Candle]) -> dict[str, tuple[list[dict[str, Any]], list[datetime]]]:
    out: dict[str, tuple[list[dict[str, Any]], list[datetime]]] = {}
    for symbol, rows in group_candles_by_symbol(raw_5m).items():
        ctx = build_basic_context(rows, fast_len=8, slow_len=21, atr_len=8, volume_len=12, range_len=36, min_history_bars=24)
        out[symbol] = (ctx, [r["time"] for r in ctx])
    return out


def classify_micro(side: str, micro: dict[str, Any] | None) -> str:
    if not micro:
        return "missing"
    side = side.lower()
    direction = str(micro.get("trend_direction", "neutral"))
    candle = str(micro.get("candle_signal", "neutral"))
    liq = str(micro.get("liquidity_event", "none"))
    vol_state = str(micro.get("volume_state", "normal"))

    if side == "short":
        if direction == "down" or candle in {"bear_impulse", "bear_rejection"} or liq == "high_sweep_reject":
            return "confirmed" if vol_state != "dry" else "neutral"
        if direction == "up" or candle in {"bull_impulse", "bull_rejection"} or liq == "low_sweep_reclaim":
            return "rejected"
    else:
        if direction == "up" or candle in {"bull_impulse", "bull_rejection"} or liq == "low_sweep_reclaim":
            return "confirmed" if vol_state != "dry" else "neutral"
        if direction == "down" or candle in {"bear_impulse", "bear_rejection"} or liq == "high_sweep_reject":
            return "rejected"
    return "neutral"


def enrich_generated_trades(path: Path, micro_ctx: dict[str, tuple[list[dict[str, Any]], list[datetime]]]) -> list[dict[str, str]]:
    rows = read_csv(path)
    enriched: list[dict[str, str]] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("side", "")).lower()
        entry_time = parse_dt(str(row.get("entry_time", "")))
        ctx_rows, ctx_times = micro_ctx.get(symbol, ([], []))
        micro = latest_context(ctx_rows, ctx_times, entry_time)
        state = classify_micro(side, micro)
        row["micro_confirm_state"] = state
        row["micro_trend_direction"] = str((micro or {}).get("trend_direction", ""))
        row["micro_candle_signal"] = str((micro or {}).get("candle_signal", ""))
        row["micro_liquidity_event"] = str((micro or {}).get("liquidity_event", ""))
        row["micro_volume_state"] = str((micro or {}).get("volume_state", ""))
        row["micro_range_position"] = str((micro or {}).get("range_position", ""))
        reason = row.get("risk_plan_reason", "")
        row["risk_plan_reason"] = (
            f"{reason}|micro={state}|micro_dir={row['micro_trend_direction']}|"
            f"micro_candle={row['micro_candle_signal']}|micro_liq={row['micro_liquidity_event']}|"
            f"micro_vol_state={row['micro_volume_state']}|micro_pos={row['micro_range_position']}"
        )
        enriched.append(row)
    write_csv(path, enriched)
    return enriched


def micro_filter_rows(rows: list[dict[str, str]], cfg: dict[str, Any]) -> list[dict[str, str]]:
    allowed = {str(x) for x in cfg.get("allowed_micro_confirm_states", ()) if str(x)}
    blocked = {str(x) for x in cfg.get("blocked_micro_confirm_states", ()) if str(x)}
    out = []
    for row in rows:
        state = str(row.get("micro_confirm_state", ""))
        if allowed and state not in allowed:
            continue
        if blocked and state in blocked:
            continue
        out.append(row)
    return out


def cfg_tuple(cfg: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in cfg.get(key, ()) if str(item).strip())


def pipeline_cfg(cfg_spec: dict[str, Any]) -> PipelineConfig:
    return replace(
        PipelineConfig(),
        name=str(cfg_spec["name"]),
        rolling_top_n=8,
        require_rolling_top=bool(cfg_spec.get("require_rolling_top", False)),
        require_universe_gate=bool(cfg_spec.get("require_universe_gate", False)),
        quality_take_threshold=float(cfg_spec["quality_take_threshold"]),
        quality_watch_threshold=float(cfg_spec["quality_watch_threshold"]),
        structure_take_threshold=float(cfg_spec["structure_take_threshold"]),
        structure_watch_threshold=float(cfg_spec["structure_watch_threshold"]),
        min_volume_ratio=float(cfg_spec.get("min_volume_ratio", 0.0)),
        **{key: cfg_tuple(cfg_spec, key) for key in FILTER_KEYS},
    )


def run_config(cfg_spec: dict[str, Any], candles_15m: Path, micro_ctx: dict[str, tuple[list[dict[str, Any]], list[datetime]]], out_dir: Path, profile: str, min_confidence: float) -> dict[str, Any]:
    name = str(cfg_spec["name"])
    run_dir = out_dir / name
    candle_summary = run_candle_pipeline(candles_csv=candles_15m, out_dir=run_dir, min_confidence=min_confidence)
    generated = run_dir / "generated_trades.csv"
    enriched = enrich_generated_trades(generated, micro_ctx)
    filtered = micro_filter_rows(enriched, cfg_spec)
    pipeline_input = run_dir / "generated_trades_micro_filtered.csv"
    write_csv(pipeline_input, filtered)

    summary = run_pipeline(input_csv=pipeline_input, out_dir=run_dir, cfg=pipeline_cfg(cfg_spec), profile_name=profile)
    allowed_trades = run_dir / "pipeline_allowed_trades.csv"
    write_pipeline_allowed_trades(pipeline_input, run_dir / "pipeline_decisions.csv", allowed_trades)
    run_paper_mode(generated_trades_csv=allowed_trades, out_dir=run_dir / "paper")
    sanity = write_report_sanity(run_dir)
    diagnosis, flags = build_diagnosis(run_dir)
    (run_dir / "research_diagnosis.md").write_text(diagnosis, encoding="utf-8")

    generated_count = int(candle_summary.get("generated_trades", 0))
    micro_filtered = len(filtered)
    allowed_candidates = int(summary.allowed_candidates)
    row: dict[str, Any] = {
        "name": name,
        "require_rolling_top": cfg_spec.get("require_rolling_top", False),
        "require_universe_gate": cfg_spec.get("require_universe_gate", False),
        "min_confidence": cfg_spec.get("min_confidence", min_confidence),
        "quality_take_threshold": cfg_spec["quality_take_threshold"],
        "quality_watch_threshold": cfg_spec["quality_watch_threshold"],
        "structure_take_threshold": cfg_spec["structure_take_threshold"],
        "structure_watch_threshold": cfg_spec["structure_watch_threshold"],
        "min_volume_ratio": cfg_spec.get("min_volume_ratio", 0.0),
        **{f"{key}_filter": ";".join(cfg_tuple(cfg_spec, key)) for key in FILTER_KEYS},
        "allowed_micro_confirm_states_filter": ";".join(cfg_tuple(cfg_spec, "allowed_micro_confirm_states")),
        "blocked_micro_confirm_states_filter": ";".join(cfg_tuple(cfg_spec, "blocked_micro_confirm_states")),
        "generated_trades": generated_count,
        "micro_filtered_trades": micro_filtered,
        "micro_allowed_pct": round(micro_filtered / generated_count * 100.0, 2) if generated_count else 0.0,
        "allowed_candidates": allowed_candidates,
        "allowed_pct": round(allowed_candidates / generated_count * 100.0, 2) if generated_count else 0.0,
        "executed_trades": summary.executed_trades,
        "ret_pct": summary.ret_pct,
        "max_dd_pct": summary.max_dd_pct,
        "pf": summary.pf,
        "winrate": summary.winrate,
        "avg_risk_pct": summary.avg_risk_pct,
        "sanity_status": sanity.status,
        "diagnosis_flags": ";".join(flags),
        "out_dir": str(run_dir),
    }
    row["score"] = score_row(row)
    return row


def write_baseline_candidate(root: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    baseline_dir = root / "baseline_candidate"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    candidate = normalize_row({key: str(value) for key, value in rows[0].items()})
    candidate["source_matrix"] = str(root / "matrix_summary.csv")
    candidate["micro_confirmation_note"] = "5m confirmation A/B candidate; research only"
    (baseline_dir / "baseline_candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(baseline_dir / "baseline_candidate.md", candidate, [{key: str(value) for key, value in row.items()} for row in rows])


def write_md(path: Path, rows: list[dict[str, Any]]) -> None:
    best = rows[0] if rows else {}
    lines = [
        "# Tagged MTF 5m Confirmation Matrix",
        "",
        "Research-only A/B test. 15m entry is rebuilt from 5m public candles; 5m is used only as micro-confirmation.",
        "",
        f"Best config: **{best.get('name', 'none')}**",
        f"Return: {best.get('ret_pct', '')}%",
        f"PF: {best.get('pf', '')}",
        f"Max DD: {best.get('max_dd_pct', '')}%",
        f"Executed trades: {best.get('executed_trades', '')}",
        f"Micro allowed: {best.get('micro_allowed_pct', '')}%",
        "",
        "## All configs",
    ]
    for row in rows:
        lines.append(
            f"- **{row['name']}**: score={row['score']}, ret={row['ret_pct']}%, pf={row['pf']}, "
            f"dd={row['max_dd_pct']}%, executed={row['executed_trades']}, micro_allowed={row['micro_allowed_pct']}%, "
            f"allowed={row['allowed_pct']}%, sanity={row['sanity_status']}, flags={row['diagnosis_flags'] or 'none'}"
        )
    lines += [
        "",
        "## Decision rule",
        "- Keep 5m only if it improves PF/DD and does not make the strategy too sparse.",
        "- If 5m variants are worse than 15m baseline, reject 5m confirmation for now.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--symbols-file", default=None)
    ap.add_argument("--limit", type=int, default=7500)
    ap.add_argument("--raw-5m-out", default="results/tagged_universe_research/micro_5m/data/raw_5m_candles.csv")
    ap.add_argument("--candles-15m-out", default="results/tagged_universe_research/micro_5m/data/rebuilt_15m_candles.csv")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/micro_5m/matrix")
    ap.add_argument("--profile", default="growth_100_20x")
    ap.add_argument("--sleep-sec", type=float, default=0.02)
    args = ap.parse_args()

    symbols = resolve_symbols(args.symbols, args.symbols_file)
    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)

    summary = load_binance_futures_candles(symbols=symbols, out_csv=args.raw_5m_out, interval="5m", limit=args.limit, sleep_sec=args.sleep_sec)
    print("5m data summary")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    if summary.status == "EMPTY":
        return 1

    raw_5m = read_candles_csv(args.raw_5m_out)
    candles_15m = resample_5m_to_15m(raw_5m)
    write_candles_csv(args.candles_15m_out, candles_15m)
    micro_ctx = build_micro_context(raw_5m)

    rows = []
    for cfg_spec in MICRO_CONFIGS:
        print(f"\n=== Running {cfg_spec['name']} ===")
        rows.append(run_config(cfg_spec, Path(args.candles_15m_out), micro_ctx, root, args.profile, float(cfg_spec["min_confidence"])))

    rows = sorted(rows, key=sort_key, reverse=True)
    write_csv(root / "matrix_summary.csv", rows)
    write_baseline_candidate(root, rows)
    write_md(root / "matrix_summary.md", rows)
    print(root / "matrix_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
