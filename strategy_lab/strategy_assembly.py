#!/usr/bin/env python3
"""Full research assembly for the current strategy stack.

Combines:
- rolling symbol selection
- trade quality scoring
- structure learning

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from strategy_lab.rolling_symbol_strength import (
    CapitalConfig,
    CostConfig,
    RollingConfig,
    build_rolling_trades,
    load_trades_csv,
    max_loss_streak,
    pf,
    simulate_capital,
)
from strategy_lab.structure_learning import (
    StructureLearningConfig,
    read_trade_rows as read_structure_rows,
    score_structure_trades,
)
from strategy_lab.trade_quality_score import (
    QualityConfig,
    read_trade_rows as read_quality_rows,
    score_trades as score_quality_trades,
)


@dataclass(frozen=True)
class AssemblyConfig:
    start: str = "2025-01-01"
    end: str = "2026-05-31"
    rolling_lookback_days: int = 30
    rolling_rebalance_days: int = 7
    rolling_top_n: int = 5
    quality_lookback_days: int = 30
    quality_min_history_trades: int = 3
    quality_take_threshold: float = 65.0
    quality_watch_threshold: float = 50.0
    structure_lookback_days: int = 30
    structure_min_exact_trades: int = 8
    structure_min_fallback_trades: int = 20
    structure_take_threshold: float = 64.0
    structure_watch_threshold: float = 52.0
    initial_cash: float = 500.0
    risk_pct: float = 0.005
    leverage: float = 20.0
    max_positions: int = 2
    max_margin_pct: float = 0.20
    fee_rate: float = 0.0010
    slippage_rate: float = 0.0002
    reinvest: bool = False


@dataclass(frozen=True)
class AssemblyRow:
    scenario: str
    candidates: int
    winrate: float
    avg_r: float
    total_r: float
    raw_pf: float
    symbols: int
    exec_trades: int
    capital_skipped: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    capital_pf: float
    capital_winrate: float
    max_loss_streak: int
    symbols_traded: int
    symbols_positive: int


@dataclass(frozen=True)
class GateMatrixRow:
    universe: str
    quality_decision: str
    structure_decision: str
    trades: int
    share_pct: float
    winrate: float
    avg_r: float
    total_r: float
    pf: float


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    txt = str(value).strip().replace("Z", "")
    return datetime.fromisoformat(txt)


def trade_key(symbol: str, side: str, entry_time: str | datetime) -> tuple[str, str, datetime]:
    return (symbol.upper(), side.lower(), parse_dt(entry_time))


def raw_stats(trades: list[Any]) -> dict[str, float | int]:
    vals = [float(t.r_mult) for t in trades]
    wins = sum(1 for v in vals if v > 0)
    return {
        "candidates": len(trades),
        "winrate": round(wins / len(vals) * 100.0, 2) if vals else 0.0,
        "avg_r": round(mean(vals), 4) if vals else 0.0,
        "total_r": round(sum(vals), 4),
        "raw_pf": round(pf(vals), 4),
        "symbols": len({t.symbol for t in trades}),
    }


def make_assembly_row(name: str, trades: list[Any], cap: CapitalConfig, cost: CostConfig) -> AssemblyRow:
    raw = raw_stats(trades)
    result = simulate_capital(trades, cap, cost, name)
    return AssemblyRow(
        scenario=name,
        candidates=int(raw["candidates"]),
        winrate=float(raw["winrate"]),
        avg_r=float(raw["avg_r"]),
        total_r=float(raw["total_r"]),
        raw_pf=float(raw["raw_pf"]),
        symbols=int(raw["symbols"]),
        exec_trades=result.trades,
        capital_skipped=result.skipped,
        final_cash=round(result.final_cash, 2),
        ret_pct=round(result.ret_pct, 2),
        max_dd_pct=round(result.max_dd_pct, 2),
        capital_pf=round(result.pf, 4),
        capital_winrate=round(result.winrate, 2),
        max_loss_streak=result.max_loss_streak,
        symbols_traded=result.symbols_traded,
        symbols_positive=result.symbols_positive,
    )


def build_gate_matrix(keys: list[tuple[str, str, datetime]], trade_by_key: dict[tuple[str, str, datetime], Any], quality_by_key: dict[tuple[str, str, datetime], Any], structure_by_key: dict[tuple[str, str, datetime], Any], rolling_keys: set[tuple[str, str, datetime]]) -> list[GateMatrixRow]:
    rolling = [k for k in keys if k in rolling_keys]
    out: list[GateMatrixRow] = []
    for q_decision in ["TAKE", "WATCH", "SKIP"]:
        for s_decision in ["TAKE", "WATCH", "SKIP"]:
            selected = [
                k for k in rolling
                if quality_by_key[k].decision == q_decision
                and structure_by_key[k].structure_decision == s_decision
            ]
            vals = [trade_by_key[k].r_mult for k in selected]
            wins = sum(1 for v in vals if v > 0)
            out.append(GateMatrixRow(
                universe="ROLLING_TOP5",
                quality_decision=q_decision,
                structure_decision=s_decision,
                trades=len(selected),
                share_pct=round(len(selected) / len(rolling) * 100.0, 2) if rolling else 0.0,
                winrate=round(wins / len(vals) * 100.0, 2) if vals else 0.0,
                avg_r=round(mean(vals), 4) if vals else 0.0,
                total_r=round(sum(vals), 4),
                pf=round(pf(vals), 4),
            ))
    return out


def write_csv(path: str | Path, rows: list[Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    data = [asdict(r) for r in rows] if hasattr(rows[0], "__dataclass_fields__") else rows
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def run_strategy_assembly_report(input_csv: str | Path, out_dir: str | Path = "results", cfg: AssemblyConfig | None = None) -> list[AssemblyRow]:
    cfg = cfg or AssemblyConfig()
    cost = CostConfig(fee_rate=cfg.fee_rate, slippage_rate=cfg.slippage_rate)
    cap = CapitalConfig(
        initial_cash=cfg.initial_cash,
        risk_pct=cfg.risk_pct,
        leverage=cfg.leverage,
        max_positions=cfg.max_positions,
        max_margin_pct=cfg.max_margin_pct,
        reinvest=cfg.reinvest,
    )

    all_trades = load_trades_csv(input_csv)
    trade_by_key = {trade_key(t.symbol, t.side, t.entry_time): t for t in all_trades}
    keys = list(trade_by_key.keys())

    rolling_trades, _windows, _avg_selected = build_rolling_trades(
        all_trades,
        parse_dt(cfg.start),
        parse_dt(cfg.end),
        RollingConfig(cfg.rolling_lookback_days, cfg.rolling_rebalance_days, cfg.rolling_top_n),
        cost,
    )
    rolling_keys = {trade_key(t.symbol, t.side, t.entry_time) for t in rolling_trades}

    quality_cfg = QualityConfig(
        lookback_days=cfg.quality_lookback_days,
        min_history_trades=cfg.quality_min_history_trades,
        take_threshold=cfg.quality_take_threshold,
        watch_threshold=cfg.quality_watch_threshold,
    )
    quality_rows = score_quality_trades(read_quality_rows(input_csv), quality_cfg)
    quality_by_key = {trade_key(r.symbol, r.side, r.entry_time): r for r in quality_rows}

    structure_cfg = StructureLearningConfig(
        lookback_days=cfg.structure_lookback_days,
        min_exact_trades=cfg.structure_min_exact_trades,
        min_fallback_trades=cfg.structure_min_fallback_trades,
        take_threshold=cfg.structure_take_threshold,
        watch_threshold=cfg.structure_watch_threshold,
    )
    structure_rows = score_structure_trades(read_structure_rows(input_csv), structure_cfg)
    structure_by_key = {trade_key(r.symbol, r.side, r.entry_time): r for r in structure_rows}

    def q_take(k: tuple[str, str, datetime]) -> bool:
        return quality_by_key[k].decision == "TAKE"

    def q_take_or_watch(k: tuple[str, str, datetime]) -> bool:
        return quality_by_key[k].decision in {"TAKE", "WATCH"}

    def s_take(k: tuple[str, str, datetime]) -> bool:
        return structure_by_key[k].structure_decision == "TAKE"

    def s_take_or_watch(k: tuple[str, str, datetime]) -> bool:
        return structure_by_key[k].structure_decision in {"TAKE", "WATCH"}

    scenarios: list[tuple[str, Callable[[tuple[str, str, datetime]], bool]]] = [
        ("ALL", lambda k: True),
        ("ROLLING_TOP5", lambda k: k in rolling_keys),
        ("QUALITY_TAKE", q_take),
        ("STRUCTURE_TAKE", s_take),
        ("QUALITY_AND_STRUCTURE_TAKE", lambda k: q_take(k) and s_take(k)),
        ("ROLLING_AND_QUALITY_TAKE", lambda k: k in rolling_keys and q_take(k)),
        ("ROLLING_AND_STRUCTURE_TAKE", lambda k: k in rolling_keys and s_take(k)),
        ("FULL_STRICT", lambda k: k in rolling_keys and q_take(k) and s_take(k)),
        ("FULL_BALANCED", lambda k: k in rolling_keys and q_take_or_watch(k) and s_take_or_watch(k)),
        ("FULL_QUALITY_GATE", lambda k: k in rolling_keys and q_take(k) and s_take_or_watch(k)),
        ("FULL_STRUCTURE_GATE", lambda k: k in rolling_keys and s_take(k) and q_take_or_watch(k)),
        ("FULL_NOT_SKIP", lambda k: k in rolling_keys and quality_by_key[k].decision != "SKIP" and structure_by_key[k].structure_decision != "SKIP"),
    ]

    report: list[AssemblyRow] = []
    for name, predicate in scenarios:
        selected = sorted(
            [trade_by_key[k] for k in keys if predicate(k)],
            key=lambda t: (t.entry_time, t.symbol, t.side),
        )
        report.append(make_assembly_row(name, selected, cap, cost))

    out = Path(out_dir)
    write_csv(out / "strategy_assembly_report.csv", report)
    write_csv(out / "strategy_assembly_gate_matrix.csv", build_gate_matrix(keys, trade_by_key, quality_by_key, structure_by_key, rolling_keys))
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--rolling-lookback-days", type=int, default=30)
    p.add_argument("--rolling-rebalance-days", type=int, default=7)
    p.add_argument("--rolling-top-n", type=int, default=5)
    p.add_argument("--leverage", type=float, default=20.0)
    args = p.parse_args()
    cfg = AssemblyConfig(
        start=args.start,
        end=args.end,
        rolling_lookback_days=args.rolling_lookback_days,
        rolling_rebalance_days=args.rolling_rebalance_days,
        rolling_top_n=args.rolling_top_n,
        leverage=args.leverage,
    )
    rows = run_strategy_assembly_report(args.input, args.out_dir, cfg)
    print("Strategy assembly report complete")
    for row in rows:
        print(
            f"{row.scenario}: candidates={row.candidates} rawPF={row.raw_pf} "
            f"exec={row.exec_trades} ret={row.ret_pct}% capPF={row.capital_pf} DD={row.max_dd_pct}%"
        )


if __name__ == "__main__":
    main()
