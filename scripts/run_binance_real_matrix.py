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


BEST_RESEARCH_SYMBOLS = ("INJUSDT", "TONUSDT", "DOGEUSDT", "ARBUSDT", "NEARUSDT", "OPUSDT")
BEST_RESEARCH_SETUPS = ("liquidity_reclaim", "pullback", "range_rotation", "ignition")
GOOD_LIQUIDITY_STATES = ("low_sweep_reclaim", "none")
BAD_LIQUIDITY_STATES = ("high_sweep_reject",)
BAD_CANDLE_TYPES = ("bear_rejection",)
BAD_DIRECTION_CONTEXTS = ("up",)


def base_cfg(name: str, **overrides: object) -> dict:
    cfg = {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": True,
        "require_universe_gate": True,
        "min_confidence": 40.0,
        "quality_take_threshold": 65.0,
        "quality_watch_threshold": 50.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 52.0,
    }
    cfg.update(overrides)
    return cfg


def micro_strict_cfg(name: str, **overrides: object) -> dict:
    """Strategy-first micro strict logic.

    By default this does NOT hard-code allowed symbols. It should be used to test
    whether the strategy logic survives on a dynamic universe instead of only on
    hand-picked core coins.
    """
    cfg = base_cfg(
        name,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
        allowed_liquidity_states=GOOD_LIQUIDITY_STATES,
        blocked_candle_types=BAD_CANDLE_TYPES,
        blocked_direction_contexts=BAD_DIRECTION_CONTEXTS,
        min_volume_ratio=0.84,
    )
    cfg.update(overrides)
    return cfg


MATRIX_CONFIGS = [
    base_cfg("BASE_T5_C40", rolling_top_n=5),
    base_cfg("MORE_COINS_T8_C40"),
    base_cfg("MORE_COINS_T10_C35", rolling_top_n=10, min_confidence=35.0),
    base_cfg(
        "SOFTER_GATES_T8_C35",
        min_confidence=35.0,
        quality_take_threshold=60.0,
        quality_watch_threshold=45.0,
        structure_take_threshold=60.0,
        structure_watch_threshold=48.0,
    ),
    base_cfg(
        "EXPLORATORY_T15_C30",
        rolling_top_n=15,
        min_confidence=30.0,
        quality_take_threshold=55.0,
        quality_watch_threshold=40.0,
        structure_take_threshold=55.0,
        structure_watch_threshold=42.0,
    ),
    base_cfg(
        "DISCOVERY_T15_C25",
        rolling_top_n=15,
        min_confidence=25.0,
        quality_take_threshold=50.0,
        quality_watch_threshold=35.0,
        structure_take_threshold=50.0,
        structure_watch_threshold=38.0,
    ),
    base_cfg(
        "WIDE_UNIVERSE_T20_C25",
        rolling_top_n=20,
        min_confidence=25.0,
        quality_take_threshold=50.0,
        quality_watch_threshold=35.0,
        structure_take_threshold=48.0,
        structure_watch_threshold=35.0,
    ),
    base_cfg("TACTICAL_NO_BREAKOUT_T8_C40", blocked_setup_types=("breakout",)),
    base_cfg("TACTICAL_NO_BREAKOUT_NO_HIGHVOL", blocked_setup_types=("breakout",), blocked_volatility_regimes=("high",)),
    base_cfg("TACTICAL_BEST_SYMBOLS_CORE", allowed_symbols=BEST_RESEARCH_SYMBOLS, blocked_setup_types=("breakout",), blocked_volatility_regimes=("high",)),
    base_cfg("TACTICAL_CORE_NO_ROLLING", require_rolling_top=False, allowed_symbols=BEST_RESEARCH_SYMBOLS, blocked_setup_types=("breakout",), blocked_volatility_regimes=("high",)),
    base_cfg("TACTICAL_CORE_DIRECT", require_rolling_top=False, require_universe_gate=False, allowed_symbols=BEST_RESEARCH_SYMBOLS, blocked_setup_types=("breakout",), blocked_volatility_regimes=("high",)),
    base_cfg(
        "TACTICAL_CORE_DIRECT_STRICTER",
        require_rolling_top=False,
        require_universe_gate=False,
        min_confidence=45.0,
        quality_take_threshold=68.0,
        quality_watch_threshold=55.0,
        structure_take_threshold=66.0,
        structure_watch_threshold=55.0,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
    ),
    base_cfg("TACTICAL_NO_BREAKOUT_NO_HIGHVOL_NO_ROLLING", require_rolling_top=False, blocked_setup_types=("breakout",), blocked_volatility_regimes=("high",)),
    base_cfg(
        "TACTICAL_GOOD_SETUPS_ONLY",
        rolling_top_n=10,
        min_confidence=35.0,
        quality_take_threshold=60.0,
        quality_watch_threshold=45.0,
        structure_take_threshold=60.0,
        structure_watch_threshold=48.0,
        allowed_setup_types=BEST_RESEARCH_SETUPS,
        blocked_volatility_regimes=("high",),
    ),
    base_cfg("STRICT_T5_C50", rolling_top_n=5, min_confidence=50.0, quality_take_threshold=70.0, quality_watch_threshold=55.0, structure_take_threshold=68.0, structure_watch_threshold=56.0),
    base_cfg(
        "TACTICAL_CORE_DIRECT_NO_BAD_LIQ",
        require_rolling_top=False,
        require_universe_gate=False,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
        blocked_liquidity_states=BAD_LIQUIDITY_STATES,
    ),
    base_cfg(
        "TACTICAL_CORE_DIRECT_NO_BEAR_REJECT",
        require_rolling_top=False,
        require_universe_gate=False,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
        blocked_candle_types=BAD_CANDLE_TYPES,
    ),
    base_cfg(
        "TACTICAL_CORE_DIRECT_MIN_VR_084",
        require_rolling_top=False,
        require_universe_gate=False,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
        min_volume_ratio=0.84,
    ),
    base_cfg(
        "TACTICAL_CORE_DIRECT_MICRO_FILTERED",
        require_rolling_top=False,
        require_universe_gate=False,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
        blocked_setup_types=("breakout",),
        blocked_volatility_regimes=("high",),
        blocked_liquidity_states=BAD_LIQUIDITY_STATES,
        blocked_candle_types=BAD_CANDLE_TYPES,
        min_volume_ratio=0.84,
    ),
    micro_strict_cfg(
        "TACTICAL_CORE_DIRECT_MICRO_STRICT",
        require_rolling_top=False,
        require_universe_gate=False,
        allowed_symbols=BEST_RESEARCH_SYMBOLS,
    ),
    # Strategy-first dynamic universe tests. These are intentionally NOT allowed_symbols-limited.
    # They answer the overfitting question: does the logic work beyond the hand-picked core?
    micro_strict_cfg("DYNAMIC_MICRO_STRICT_T8", rolling_top_n=8, require_rolling_top=True, require_universe_gate=True),
    micro_strict_cfg("DYNAMIC_MICRO_STRICT_T12", rolling_top_n=12, require_rolling_top=True, require_universe_gate=True),
    micro_strict_cfg("DYNAMIC_MICRO_STRICT_T20", rolling_top_n=20, require_rolling_top=True, require_universe_gate=True),
    micro_strict_cfg(
        "DYNAMIC_MICRO_STRICTER_T12",
        rolling_top_n=12,
        require_rolling_top=True,
        require_universe_gate=True,
        min_confidence=45.0,
        quality_take_threshold=68.0,
        quality_watch_threshold=55.0,
        structure_take_threshold=66.0,
        structure_watch_threshold=55.0,
    ),
    micro_strict_cfg(
        "NEW_COINS_DISCOVERY_MICRO_STRICT_T20",
        rolling_top_n=20,
        require_rolling_top=True,
        require_universe_gate=True,
        blocked_symbols=BEST_RESEARCH_SYMBOLS,
    ),
]


TACTICAL_FILTER_KEYS = [
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


def to_bool(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def score_row(row: dict) -> float:
    executed = float(row.get("executed_trades", 0) or 0)
    ret = float(row.get("ret_pct", 0) or 0)
    dd = abs(float(row.get("max_dd_pct", 0) or 0))
    pf_raw = float(row.get("pf", 0) or 0)
    pf = min(pf_raw, 3.0)
    allowed_pct = float(row.get("allowed_pct", 0) or 0)
    sanity_status = row.get("sanity_status")
    sanity_penalty = 50.0 if sanity_status == "FAIL" else 15.0 if sanity_status == "WARN" else 0.0
    sparse_penalty = max(0.0, 20.0 - executed) * 3.0
    ultra_sparse_penalty = 35.0 if executed < 5 else 0.0
    overfilter_penalty = max(0.0, 1.0 - allowed_pct) * 8.0

    # Avoid rewarding a fixed-symbol core just because it was hand-picked.
    # The score should prefer robust strategy logic, not a cherry-picked coin list.
    has_explicit_allowlist = bool(str(row.get("allowed_symbols_filter", "")).strip())
    fixed_symbol_penalty = 0.25 if has_explicit_allowlist else 0.0

    return round(
        ret
        + (pf * 4.0)
        + min(allowed_pct, 25.0) * 0.2
        - dd * 0.5
        - sanity_penalty
        - sparse_penalty
        - ultra_sparse_penalty
        - overfilter_penalty
        - fixed_symbol_penalty,
        4,
    )


def cfg_tuple(cfg_spec: dict, key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in cfg_spec.get(key, ()) if str(item).strip())


def sort_key(row: dict) -> tuple[float, float, float, int]:
    return (
        float(row.get("score", 0) or 0),
        float(row.get("ret_pct", 0) or 0),
        float(row.get("pf", 0) or 0),
        int(float(row.get("executed_trades", 0) or 0)),
    )


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
    if market_summary.status == "EMPTY":
        return 1
    if market_summary.status == "PARTIAL":
        print("WARNING: Continuing matrix with partial market data after unavailable/stale symbols were skipped.")

    rows: list[dict] = []
    for cfg_spec in MATRIX_CONFIGS:
        name = cfg_spec["name"]
        run_dir = root / name
        cfg = replace(
            PipelineConfig(),
            name=name,
            rolling_top_n=int(cfg_spec["rolling_top_n"]),
            require_rolling_top=bool(cfg_spec.get("require_rolling_top", True)),
            require_universe_gate=bool(cfg_spec.get("require_universe_gate", True)),
            quality_take_threshold=float(cfg_spec["quality_take_threshold"]),
            quality_watch_threshold=float(cfg_spec["quality_watch_threshold"]),
            structure_take_threshold=float(cfg_spec["structure_take_threshold"]),
            structure_watch_threshold=float(cfg_spec["structure_watch_threshold"]),
            min_volume_ratio=float(cfg_spec.get("min_volume_ratio", 0.0)),
            **{key: cfg_tuple(cfg_spec, key) for key in TACTICAL_FILTER_KEYS},
        )
        print(f"\n=== Running {name} ===")
        summary = run_end_to_end_pipeline(
            candles_csv=args.candles_out,
            out_dir=run_dir,
            profile=args.profile,
            min_confidence=float(cfg_spec["min_confidence"]),
            cfg=cfg,
        )
        diagnosis, flags = build_diagnosis(run_dir)
        (run_dir / "research_diagnosis.md").write_text(diagnosis, encoding="utf-8")
        generated = int(summary.generated_trades)
        allowed = int(summary.allowed_candidates)
        row = {
            "name": name,
            "rolling_top_n": cfg.rolling_top_n,
            "require_rolling_top": cfg.require_rolling_top,
            "require_universe_gate": cfg.require_universe_gate,
            "min_confidence": cfg_spec["min_confidence"],
            "quality_take_threshold": cfg.quality_take_threshold,
            "quality_watch_threshold": cfg.quality_watch_threshold,
            "structure_take_threshold": cfg.structure_take_threshold,
            "structure_watch_threshold": cfg.structure_watch_threshold,
            "min_volume_ratio": cfg.min_volume_ratio,
            **{f"{key}_filter": ";".join(getattr(cfg, key)) for key in TACTICAL_FILTER_KEYS},
            "generated_trades": generated,
            "allowed_candidates": allowed,
            "allowed_pct": round(allowed / generated * 100.0, 2) if generated else 0.0,
            "executed_trades": summary.executed_trades,
            "ret_pct": summary.ret_pct,
            "max_dd_pct": summary.max_dd_pct,
            "pf": summary.pf,
            "winrate": summary.winrate,
            "avg_risk_pct": summary.avg_risk_pct,
            "paper_decision": getattr(summary, "paper_decision", ""),
            "paper_avg_pnl_pct": getattr(summary, "paper_avg_pnl_pct", 0.0),
            "sanity_status": summary.sanity_status,
            "diagnosis_flags": ";".join(flags),
            "out_dir": str(run_dir),
        }
        row["score"] = score_row(row)
        rows.append(row)
        print(f"{name}: ret={summary.ret_pct}% dd={summary.max_dd_pct}% pf={summary.pf} executed={summary.executed_trades} sanity={summary.sanity_status} score={row['score']}")

    rows = sorted(rows, key=sort_key, reverse=True)
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
        f"Require rolling top: {best.get('require_rolling_top', '')}",
        f"Require universe gate: {best.get('require_universe_gate', '')}",
        f"Min volume ratio: {best.get('min_volume_ratio', '')}",
        "",
        "## All configs",
    ]
    for row in rows:
        lines.append(
            f"- {row['name']}: score={row['score']}, ret={row['ret_pct']}%, dd={row['max_dd_pct']}%, "
            f"pf={row['pf']}, executed={row['executed_trades']}, allowed={row['allowed_pct']}%, "
            f"rolling_required={row['require_rolling_top']}, universe_required={row['require_universe_gate']}, "
            f"fixed_allowlist={'yes' if row.get('allowed_symbols_filter') else 'no'}, "
            f"min_vr={row['min_volume_ratio']}, sanity={row['sanity_status']}"
        )
    lines.append("")
    lines.append("## Next step")
    if best and float(best.get("executed_trades", 0) or 0) < 20:
        lines.append("- Increase symbols/history or relax gates before judging the strategy; best config is still too sparse.")
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
