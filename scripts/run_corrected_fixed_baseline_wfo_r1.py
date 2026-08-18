#!/usr/bin/env python3
"""Corrected fixed-baseline walk-forward audit for Smoke Strategy.

Research-only audit runner.

Key correction versus the legacy WFO:
- warmup candles/trades are available to causal adaptive state;
- portfolio performance is calculated ONLY from trades whose entry_time is
  inside the validation interval;
- a baseline that requires the current full-sample universe gate is rejected,
  because that gate ranks symbols from complete realized trade outcomes.

This fixes warmup contamination for an already-frozen baseline. It does NOT
remove prior matrix-selection leakage. A true nested WFO is still required for
clean strategy-selection validation.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from strategy_lab.binance_market_data import load_binance_futures_candles
from strategy_lab.config import PipelineConfig, get_risk_profile
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline
from strategy_lab.portfolio_simulator import simulate_dynamic_portfolio
from strategy_lab.rolling_symbol_strength import CostConfig, load_trades_csv


DEFAULT_SYMBOLS = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,"
    "AVAXUSDT,TONUSDT,NEARUSDT,APTUSDT,ARBUSDT,OPUSDT,INJUSDT"
)


def parse_dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", "").replace("T", " "))


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


def to_bool(value: object, default: bool = False) -> bool:
    if value in {None, ""}:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def to_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(";") if part.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    p = Path(path)
    with p.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict], fields: list[str] | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or (list(rows[0].keys()) if rows else [])
    if not fieldnames:
        p.write_text("", encoding="utf-8")
        return
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def load_baseline(path: str | Path) -> dict[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if to_bool(data.get("require_universe_gate"), False):
        raise ValueError(
            "Baseline requires the current learned universe gate. That gate uses "
            "full-sample realized outcomes and is not allowed in corrected causal WFO."
        )
    return data


def baseline_cfg(
    baseline: dict[str, object],
    name: str,
    warmup_start: datetime,
    validation_end: datetime,
) -> PipelineConfig:
    return replace(
        PipelineConfig(),
        name=name,
        start=warmup_start.date().isoformat(),
        end=(validation_end + timedelta(days=1)).date().isoformat(),
        rolling_top_n=to_int(baseline.get("rolling_top_n"), 5),
        require_rolling_top=to_bool(baseline.get("require_rolling_top"), True),
        require_universe_gate=False,
        quality_take_threshold=to_float(baseline.get("quality_take_threshold"), 65.0),
        quality_watch_threshold=to_float(baseline.get("quality_watch_threshold"), 50.0),
        structure_take_threshold=to_float(baseline.get("structure_take_threshold"), 64.0),
        structure_watch_threshold=to_float(baseline.get("structure_watch_threshold"), 52.0),
        min_volume_ratio=to_float(baseline.get("min_volume_ratio"), 0.0),
        allowed_symbols=to_tuple(baseline.get("allowed_symbols")),
        blocked_symbols=to_tuple(baseline.get("blocked_symbols")),
        allowed_setup_types=to_tuple(baseline.get("allowed_setup_types")),
        blocked_setup_types=to_tuple(baseline.get("blocked_setup_types")),
        allowed_trend_contexts=to_tuple(baseline.get("allowed_trend_contexts")),
        blocked_trend_contexts=to_tuple(baseline.get("blocked_trend_contexts")),
        allowed_volatility_regimes=to_tuple(baseline.get("allowed_volatility_regimes")),
        blocked_volatility_regimes=to_tuple(baseline.get("blocked_volatility_regimes")),
        allowed_liquidity_states=to_tuple(baseline.get("allowed_liquidity_states")),
        blocked_liquidity_states=to_tuple(baseline.get("blocked_liquidity_states")),
        allowed_candle_types=to_tuple(baseline.get("allowed_candle_types")),
        blocked_candle_types=to_tuple(baseline.get("blocked_candle_types")),
        allowed_direction_contexts=to_tuple(baseline.get("allowed_direction_contexts")),
        blocked_direction_contexts=to_tuple(baseline.get("blocked_direction_contexts")),
    )


def make_windows(min_time: datetime, max_time: datetime, lookback_days: int, windows: int):
    validation_start = min_time + timedelta(days=lookback_days)
    if validation_start >= max_time:
        return []
    total = (max_time - validation_start).total_seconds()
    step = total / max(1, windows)
    out = []
    cur = validation_start
    for idx in range(max(1, windows)):
        end = max_time if idx == windows - 1 else validation_start + timedelta(seconds=step * (idx + 1))
        if end > cur:
            out.append((cur - timedelta(days=lookback_days), cur, end))
        cur = end
    return out


def trade_key(row: dict[str, str]):
    return (
        str(row.get("symbol", "")).upper(),
        str(row.get("side", "")).lower(),
        parse_dt(row.get("entry_time", "")),
    )


def validation_metrics(run_dir: Path, validation_start: datetime, validation_end: datetime, profile_name: str, cfg: PipelineConfig):
    generated_rows, generated_fields = read_csv(run_dir / "generated_trades.csv")
    decision_rows, _ = read_csv(run_dir / "pipeline_decisions.csv")

    allowed_decisions = {
        trade_key(r): r
        for r in decision_rows
        if str(r.get("allowed", "")).strip().lower() == "true"
        and validation_start <= parse_dt(r.get("entry_time", "")) < validation_end
    }
    validation_rows = [
        r for r in generated_rows
        if trade_key(r) in allowed_decisions
        and validation_start <= parse_dt(r.get("entry_time", "")) < validation_end
    ]

    validation_csv = run_dir / "validation_allowed_trades.csv"
    write_csv(validation_csv, validation_rows, generated_fields)
    if not validation_rows:
        return {
            "allowed_validation_trades": 0,
            "executed_trades": 0,
            "ret_pct": 0.0,
            "max_dd_pct": 0.0,
            "pf": 0.0,
            "winrate": 0.0,
            "avg_risk_pct": 0.0,
            "final_cash": get_risk_profile(profile_name).initial_cash,
        }

    trades = load_trades_csv(validation_csv)
    risk_pcts = {
        key: to_float(row.get("risk_pct"), 0.0)
        for key, row in allowed_decisions.items()
    }
    profile = get_risk_profile(profile_name)
    cost = CostConfig(fee_rate=cfg.fee_rate, slippage_rate=cfg.slippage_rate)
    result = simulate_dynamic_portfolio(trades, risk_pcts, profile, cost, "VALIDATION_ONLY_R1")
    return {
        "allowed_validation_trades": len(validation_rows),
        "executed_trades": result.trades,
        "ret_pct": round(result.ret_pct, 4),
        "max_dd_pct": round(result.max_dd_pct, 4),
        "pf": round(result.pf, 4),
        "winrate": round(result.winrate, 4),
        "avg_risk_pct": round(result.avg_risk_pct, 6),
        "final_cash": round(result.final_cash, 4),
    }


def aggregate_verdict(rows: list[dict]) -> str:
    valid = [r for r in rows if r.get("status") == "OK"]
    if not valid:
        return "BLOCK_NO_VALID_FOLDS"
    total_trades = sum(to_int(r.get("executed_trades")) for r in valid)
    positive = sum(1 for r in valid if to_float(r.get("ret_pct")) > 0)
    avg_pf = mean([to_float(r.get("pf")) for r in valid]) if valid else 0.0
    avg_ret = mean([to_float(r.get("ret_pct")) for r in valid]) if valid else 0.0
    if total_trades < 20:
        return "WATCH_TOO_SPARSE"
    if positive == len(valid) and avg_pf >= 1.20 and avg_ret > 0:
        return "PASS_FIXED_BASELINE_AUDIT_ONLY"
    if positive >= max(1, len(valid) // 2) and avg_pf >= 1.0 and avg_ret > 0:
        return "WATCH_MIXED_FIXED_BASELINE"
    return "REJECT_FIXED_BASELINE"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", default="strategy_lab/baselines/tactical_core_direct_micro_strict.json")
    p.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    p.add_argument("--interval", default="1h")
    p.add_argument("--limit", type=int, default=1500)
    p.add_argument("--windows", type=int, default=4)
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--profile", default="growth_100_20x")
    p.add_argument("--out-dir", default="results/corrected_fixed_baseline_wfo_r1")
    p.add_argument("--candles-out", default="data/corrected_fixed_baseline_wfo_r1.csv")
    p.add_argument("--sleep-sec", type=float, default=0.05)
    args = p.parse_args()

    baseline = load_baseline(args.baseline)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    market = load_binance_futures_candles(
        symbols=symbols,
        out_csv=args.candles_out,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    if market.status != "OK":
        raise RuntimeError(f"Market data load failed: {market}")

    candle_rows, candle_fields = read_csv(args.candles_out)
    times = sorted({parse_dt(r["time"]) for r in candle_rows})
    windows = make_windows(times[0], times[-1], args.lookback_days, args.windows)
    summary_rows: list[dict] = []

    for idx, (warmup_start, validation_start, validation_end) in enumerate(windows, 1):
        fold = f"fold_{idx:02d}"
        run_dir = out / fold
        fold_candles = run_dir / "candles.csv"
        rows = [r for r in candle_rows if warmup_start <= parse_dt(r["time"]) < validation_end]
        write_csv(fold_candles, rows, candle_fields)
        cfg = baseline_cfg(baseline, f"CORRECTED_{fold}", warmup_start, validation_end)
        try:
            warmup_summary = run_end_to_end_pipeline(
                candles_csv=fold_candles,
                out_dir=run_dir,
                profile=args.profile,
                min_confidence=to_float(baseline.get("min_confidence"), 40.0),
                cfg=cfg,
            )
            metrics = validation_metrics(run_dir, validation_start, validation_end, args.profile, cfg)
            summary_rows.append({
                "fold": fold,
                "status": "OK",
                "warmup_start": warmup_start.isoformat(timespec="seconds"),
                "validation_start": validation_start.isoformat(timespec="seconds"),
                "validation_end": validation_end.isoformat(timespec="seconds"),
                "warmup_plus_validation_generated": warmup_summary.generated_trades,
                **metrics,
                "error": "",
            })
        except Exception as exc:  # continue audit folds
            summary_rows.append({
                "fold": fold,
                "status": "ERROR",
                "warmup_start": warmup_start.isoformat(timespec="seconds"),
                "validation_start": validation_start.isoformat(timespec="seconds"),
                "validation_end": validation_end.isoformat(timespec="seconds"),
                "warmup_plus_validation_generated": 0,
                "allowed_validation_trades": 0,
                "executed_trades": 0,
                "ret_pct": 0.0,
                "max_dd_pct": 0.0,
                "pf": 0.0,
                "winrate": 0.0,
                "avg_risk_pct": 0.0,
                "final_cash": get_risk_profile(args.profile).initial_cash,
                "error": str(exc),
            })

    write_csv(out / "corrected_wfo_summary.csv", summary_rows)
    verdict = aggregate_verdict(summary_rows)
    valid = [r for r in summary_rows if r["status"] == "OK"]
    report = [
        "# Corrected Fixed-Baseline WFO R1",
        "",
        f"Baseline: `{baseline.get('name', Path(args.baseline).stem)}`",
        f"Verdict: **{verdict}**",
        "",
        "Important: this fixes warmup contamination only. It does not erase any prior matrix-selection leakage in how the baseline was originally discovered.",
        "",
        f"Valid folds: {len(valid)}/{len(summary_rows)}",
        f"Validation executed trades: {sum(to_int(r.get('executed_trades')) for r in valid)}",
        f"Positive folds: {sum(1 for r in valid if to_float(r.get('ret_pct')) > 0)}/{len(valid)}" if valid else "Positive folds: 0/0",
        f"Average validation return: {round(mean([to_float(r.get('ret_pct')) for r in valid]), 4) if valid else 0.0}%",
        f"Average validation PF: {round(mean([to_float(r.get('pf')) for r in valid]), 4) if valid else 0.0}",
        f"Worst validation DD: {round(max([abs(to_float(r.get('max_dd_pct'))) for r in valid], default=0.0), 4)}%",
        "",
        "## Folds",
    ]
    for r in summary_rows:
        report.append(
            f"- {r['fold']}: status={r['status']}, validation={r['validation_start']} -> {r['validation_end']}, "
            f"trades={r['executed_trades']}, ret={r['ret_pct']}%, PF={r['pf']}, DD={r['max_dd_pct']}%"
            + (f", error={r['error']}" if r.get("error") else "")
        )
    (out / "corrected_wfo_summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
