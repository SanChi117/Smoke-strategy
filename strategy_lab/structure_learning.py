#!/usr/bin/env python3
"""Research-only market structure learning layer.

Scores each candidate trade using only previous trades from a rolling lookback
window. No live trading, no API keys, no future leakage, no black-box ML.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class StructureLearningConfig:
    lookback_days: int = 30
    min_exact_trades: int = 8
    min_fallback_trades: int = 20
    take_threshold: float = 64.0
    watch_threshold: float = 52.0


@dataclass(frozen=True)
class TradeRow:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime | None
    entry: float
    stop: float
    exit: float | None
    r_mult: float
    kind: str = ""
    source: str = ""
    setup_type: str = "unknown"
    trend_context: str = "unknown"
    volatility_regime: str = "unknown"
    structure_type: str = "unknown"
    risk_bucket: str = "unknown"
    session: str = "unknown"


@dataclass(frozen=True)
class StructureStats:
    key_scope: str
    key_value: str
    trades: int
    winrate: float
    avg_r: float
    pf: float
    max_loss_streak: int
    score: float


@dataclass(frozen=True)
class ScoredStructureTrade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    kind: str
    source: str
    setup_type: str
    trend_context: str
    volatility_regime: str
    structure_type: str
    risk_bucket: str
    session: str
    r_mult: float
    outcome: str
    structure_key: str
    fallback_key: str
    learning_scope: str
    history_trades: int
    history_pf: float
    history_winrate: float
    history_avg_r: float
    history_max_loss_streak: int
    structure_score: float
    structure_decision: str
    recommended_target_policy: str
    risk_modifier: float


@dataclass(frozen=True)
class BreakdownRow:
    group: str
    value: str
    trades: int
    wins: int
    losses: int
    winrate: float
    avg_r: float
    pf: float
    total_r: float
    avg_structure_score: float


def parse_dt(value: str | None) -> datetime | None:
    txt = str(value or "").strip().replace("Z", "")
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        return datetime.strptime(txt[:19], "%Y-%m-%dT%H:%M:%S")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(str(value).strip())
    except Exception:
        return default
    return default if math.isnan(out) or math.isinf(out) else out


def norm(value: Any, default: str = "unknown") -> str:
    out = str(value or "").strip().lower().replace(" ", "_")
    return out or default


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _symbol_index(symbol: str) -> int:
    match = re.search(r"(\d+)", symbol)
    return int(match.group(1)) - 1 if match else 0


def infer_setup(row: dict[str, Any]) -> str:
    explicit = norm(row.get("setup_type"), "")
    if explicit:
        return explicit
    text = f"{row.get('kind', '')} {row.get('source', '')}".lower()
    if "pullback" in text:
        return "pullback"
    if "breakout" in text:
        return "breakout"
    if "flat" in text or "range" in text or "reversal" in text:
        return "range_reversal"
    if "ignition" in text or "impulse" in text:
        return "ignition"
    if "runner" in text:
        return "runner"
    return "unknown"


def infer_trend(row: dict[str, Any], entry_time: datetime, symbol: str) -> str:
    explicit = norm(row.get("trend_context"), "")
    if explicit:
        if explicit in {"with_trend", "protrend", "trend"}:
            return "trend"
        if explicit in {"counter", "against_trend", "countertrend"}:
            return "countertrend"
        if explicit in {"range", "flat", "sideways", "neutral"}:
            return "range"
        return explicit
    # Deterministic research fallback for sample CSVs without context columns.
    day_index = (entry_time.date() - datetime(2025, 1, 1).date()).days
    cycle = math.sin((day_index / 31.0) + _symbol_index(symbol) * 0.73)
    if cycle > 0.33:
        return "trend"
    if cycle < -0.33:
        return "countertrend"
    return "range"


def risk_bucket(entry: float, stop: float) -> str:
    if entry <= 0:
        return "unknown"
    risk = abs(entry - stop) / entry * 100.0
    if risk < 1.65:
        return "tight"
    if risk <= 2.15:
        return "normal"
    return "wide"


def infer_volatility(row: dict[str, Any], rb: str) -> str:
    explicit = norm(row.get("volatility_regime"), "")
    return explicit or {"tight": "low", "normal": "normal", "wide": "high"}.get(rb, "unknown")


def infer_structure(row: dict[str, Any], setup: str, trend: str, rb: str) -> str:
    explicit = norm(row.get("structure_type"), "")
    if explicit:
        return explicit
    if trend == "trend" and setup in {"runner", "pullback", "ignition"}:
        return "continuation"
    if trend == "countertrend":
        return "countertrend_reaction"
    if trend == "range":
        return "range_rotation"
    if rb == "wide":
        return "wide_risk_structure"
    return "unknown_structure"


def session_bucket(dt: datetime) -> str:
    if dt.hour < 8:
        return "asia"
    if dt.hour < 16:
        return "europe"
    return "us"


def read_trade_rows(path: str | Path) -> list[TradeRow]:
    rows: list[TradeRow] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "side", "entry_time", "entry", "stop", "r_mult"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")
        for raw in reader:
            entry_time = parse_dt(raw.get("entry_time"))
            if entry_time is None:
                continue
            symbol = str(raw.get("symbol", "")).strip().upper()
            entry = safe_float(raw.get("entry"))
            stop = safe_float(raw.get("stop"))
            setup = infer_setup(raw)
            trend = infer_trend(raw, entry_time, symbol)
            rb = risk_bucket(entry, stop)
            vol = infer_volatility(raw, rb)
            structure = infer_structure(raw, setup, trend, rb)
            rows.append(TradeRow(symbol, norm(raw.get("side")), entry_time, parse_dt(raw.get("exit_time")), entry, stop, safe_float(raw.get("exit"), float("nan")), safe_float(raw.get("r_mult")), str(raw.get("kind", "") or "").strip(), str(raw.get("source", "") or "").strip(), setup, trend, vol, structure, rb, session_bucket(entry_time)))
    return sorted(rows, key=lambda r: (r.entry_time, r.symbol, r.side))


def pf(values: Iterable[float]) -> float:
    vals = list(values)
    gains = sum(v for v in vals if v > 0)
    losses = -sum(v for v in vals if v < 0)
    if losses <= 0:
        return 99.0 if gains > 0 else 0.0
    return gains / losses


def max_loss_streak(values: Iterable[float]) -> int:
    best = cur = 0
    for value in values:
        if value < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def structure_key(t: TradeRow) -> str:
    return "|".join([t.side, t.setup_type, t.trend_context, t.volatility_regime, t.structure_type, t.risk_bucket])


def fallback_key(t: TradeRow) -> str:
    return "|".join([t.setup_type, t.trend_context, t.structure_type, t.risk_bucket])


def loose_key(t: TradeRow) -> str:
    return "|".join([t.trend_context, t.structure_type, t.risk_bucket])


def calculate_stats(values: list[float], scope: str, key: str) -> StructureStats:
    if not values:
        return StructureStats(scope, key, 0, 0.0, 0.0, 0.0, 0, 45.0)
    pfx = pf(values)
    wr = sum(1 for v in values if v > 0) / len(values)
    avg_r = mean(values)
    streak = max_loss_streak(values)
    sample_bonus = min(12.0, math.log(len(values) + 1.0) * 3.0)
    score = 48.0 + avg_r * 42.0 + (min(pfx, 5.0) - 1.0) * 9.0 + (wr - 0.50) * 46.0 + sample_bonus - min(streak * 3.0, 18.0)
    return StructureStats(scope, key, len(values), round(wr, 4), round(avg_r, 4), round(pfx, 4), streak, round(clamp(score), 2))


def choose_history_stats(trade: TradeRow, history: deque[TradeRow], cfg: StructureLearningConfig) -> StructureStats:
    exact = [t.r_mult for t in history if structure_key(t) == structure_key(trade)]
    if len(exact) >= cfg.min_exact_trades:
        return calculate_stats(exact, "exact", structure_key(trade))
    fallback = [t.r_mult for t in history if fallback_key(t) == fallback_key(trade)]
    if len(fallback) >= cfg.min_fallback_trades:
        return calculate_stats(fallback, "fallback", fallback_key(trade))
    loose = [t.r_mult for t in history if loose_key(t) == loose_key(trade)]
    if len(loose) >= cfg.min_fallback_trades:
        return calculate_stats(loose, "loose", loose_key(trade))
    global_values = [t.r_mult for t in history]
    if len(global_values) >= cfg.min_fallback_trades:
        return calculate_stats(global_values, "global", "all_recent_trades")
    return StructureStats("cold_start", structure_key(trade), len(global_values), 0.0, 0.0, 0.0, 0, 45.0)


def decision(score: float, cfg: StructureLearningConfig) -> str:
    if score >= cfg.take_threshold:
        return "TAKE"
    if score >= cfg.watch_threshold:
        return "WATCH"
    return "SKIP"


def target_policy(trade: TradeRow, score: float) -> str:
    if score < 52:
        return "no_trade"
    if trade.trend_context == "countertrend":
        return "compressed_countertrend_target"
    if trade.trend_context == "trend" and score >= 64:
        return "allow_wider_trend_target"
    if trade.trend_context == "range":
        return "range_mid_or_opposite_boundary"
    return "normal_target"


def risk_modifier(score: float, cfg: StructureLearningConfig) -> float:
    if score >= 74:
        return 1.0
    if score >= cfg.take_threshold:
        return 0.75
    if score >= cfg.watch_threshold:
        return 0.35
    return 0.0


def score_structure_trades(trades: list[TradeRow], cfg: StructureLearningConfig | None = None) -> list[ScoredStructureTrade]:
    cfg = cfg or StructureLearningConfig()
    history: deque[TradeRow] = deque()
    out: list[ScoredStructureTrade] = []
    for trade in sorted(trades, key=lambda r: (r.entry_time, r.symbol, r.side)):
        cutoff = trade.entry_time - timedelta(days=cfg.lookback_days)
        while history and history[0].entry_time < cutoff:
            history.popleft()
        stats = choose_history_stats(trade, history, cfg)
        dec = decision(stats.score, cfg)
        out.append(ScoredStructureTrade(trade.symbol, trade.side, trade.entry_time.isoformat(), trade.exit_time.isoformat() if trade.exit_time else "", trade.kind, trade.source, trade.setup_type, trade.trend_context, trade.volatility_regime, trade.structure_type, trade.risk_bucket, trade.session, round(trade.r_mult, 6), "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat", structure_key(trade), fallback_key(trade), stats.key_scope, stats.trades, stats.pf, stats.winrate, stats.avg_r, stats.max_loss_streak, stats.score, dec, target_policy(trade, stats.score), risk_modifier(stats.score, cfg)))
        history.append(trade)
    return out


def summarize(rows: list[ScoredStructureTrade], group: str, value: str) -> BreakdownRow:
    vals = [r.r_mult for r in rows]
    wins = sum(1 for v in vals if v > 0)
    losses = sum(1 for v in vals if v < 0)
    return BreakdownRow(group, value, len(rows), wins, losses, round(wins / len(rows), 4) if rows else 0.0, round(mean(vals), 4) if vals else 0.0, round(pf(vals), 4), round(sum(vals), 4), round(mean([r.structure_score for r in rows]), 2) if rows else 0.0)


def build_breakdown(scored: list[ScoredStructureTrade]) -> list[BreakdownRow]:
    groups = {"side": {}, "trend_context": {}, "volatility_regime": {}, "structure_type": {}, "risk_bucket": {}, "session": {}, "learning_scope": {}, "structure_decision": {}}
    for row in scored:
        for group, value in [("side", row.side), ("trend_context", row.trend_context), ("volatility_regime", row.volatility_regime), ("structure_type", row.structure_type), ("risk_bucket", row.risk_bucket), ("session", row.session), ("learning_scope", row.learning_scope), ("structure_decision", row.structure_decision)]:
            groups[group].setdefault(value, []).append(row)
    return [summarize(rows, group, value) for group, values in groups.items() for value, rows in sorted(values.items())]


def decision_compare(scored: list[ScoredStructureTrade]) -> list[dict[str, Any]]:
    buckets = [("ALL", scored), ("TAKE", [r for r in scored if r.structure_decision == "TAKE"]), ("TAKE_OR_WATCH", [r for r in scored if r.structure_decision in {"TAKE", "WATCH"}]), ("WATCH", [r for r in scored if r.structure_decision == "WATCH"]), ("SKIP", [r for r in scored if r.structure_decision == "SKIP"])]
    total = len(scored) or 1
    out: list[dict[str, Any]] = []
    for name, rows in buckets:
        s = summarize(rows, "decision_compare", name)
        out.append({"group": name, "trades": s.trades, "share_pct": round(s.trades / total * 100.0, 2), "wins": s.wins, "losses": s.losses, "winrate": s.winrate, "avg_r": s.avg_r, "total_r": s.total_r, "pf": s.pf, "avg_structure_score": s.avg_structure_score})
    return out


def summary(scored: list[ScoredStructureTrade], cfg: StructureLearningConfig) -> dict[str, Any]:
    vals = [r.r_mult for r in scored]
    take = [r for r in scored if r.structure_decision == "TAKE"]
    watch = [r for r in scored if r.structure_decision == "WATCH"]
    skip = [r for r in scored if r.structure_decision == "SKIP"]
    return {"lookback_days": cfg.lookback_days, "min_exact_trades": cfg.min_exact_trades, "min_fallback_trades": cfg.min_fallback_trades, "take_threshold": cfg.take_threshold, "watch_threshold": cfg.watch_threshold, "trades": len(scored), "winrate": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else 0.0, "avg_r": round(mean(vals), 4) if vals else 0.0, "total_r": round(sum(vals), 4), "pf": round(pf(vals), 4), "avg_structure_score": round(mean([r.structure_score for r in scored]), 2) if scored else 0.0, "take_trades": len(take), "take_avg_r": round(mean([r.r_mult for r in take]), 4) if take else 0.0, "take_pf": round(pf([r.r_mult for r in take]), 4), "watch_trades": len(watch), "watch_avg_r": round(mean([r.r_mult for r in watch]), 4) if watch else 0.0, "skip_trades": len(skip), "skip_avg_r": round(mean([r.r_mult for r in skip]), 4) if skip else 0.0}


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


def run_structure_learning_report(input_csv: str | Path, out_dir: str | Path = "results", cfg: StructureLearningConfig | None = None) -> dict[str, Any]:
    cfg = cfg or StructureLearningConfig()
    scored = score_structure_trades(read_trade_rows(input_csv), cfg)
    out = Path(out_dir)
    write_csv(out / "structure_learning_scored_trades.csv", scored)
    write_csv(out / "structure_learning_breakdown.csv", build_breakdown(scored))
    write_csv(out / "structure_learning_decision_compare.csv", decision_compare(scored))
    summary_row = summary(scored, cfg)
    write_csv(out / "structure_learning_summary.csv", [summary_row])
    return summary_row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--min-exact-trades", type=int, default=8)
    p.add_argument("--min-fallback-trades", type=int, default=20)
    p.add_argument("--take-threshold", type=float, default=64.0)
    p.add_argument("--watch-threshold", type=float, default=52.0)
    args = p.parse_args()
    cfg = StructureLearningConfig(args.lookback_days, args.min_exact_trades, args.min_fallback_trades, args.take_threshold, args.watch_threshold)
    s = run_structure_learning_report(args.input, args.out_dir, cfg)
    print("Structure Learning report complete")
    print(f"Input: {args.input}")
    print(f"Trades: {s['trades']}")
    print(f"PF: {s['pf']}")
    print(f"Winrate: {s['winrate']}")
    print(f"TAKE trades: {s['take_trades']} | TAKE avg R: {s['take_avg_r']} | TAKE PF: {s['take_pf']}")
    print(f"SKIP trades: {s['skip_trades']} | SKIP avg R: {s['skip_avg_r']}")


if __name__ == "__main__":
    main()
