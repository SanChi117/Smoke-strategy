#!/usr/bin/env python3
"""Research-only adaptive trade quality scoring.

No live trading. No API keys. No self-modifying strategy.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class QualityConfig:
    lookback_days: int = 30
    min_history_trades: int = 3
    take_threshold: float = 65.0
    watch_threshold: float = 50.0


@dataclass
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
    trend_context: str = "unknown"
    volatility_regime: str = "unknown"
    setup_type: str = "unknown"


@dataclass
class ScoredTrade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    kind: str
    source: str
    setup_type: str
    trend_context: str
    volatility_regime: str
    r_mult: float
    outcome: str
    stop_risk_pct: float
    history_trades: int
    history_pf: float
    history_winrate: float
    history_avg_r: float
    history_max_loss_streak: int
    symbol_strength_score: float
    trend_alignment_score: float
    volatility_fit_score: float
    target_realism_score: float
    entry_quality_score: float
    trade_confidence_score: float
    decision: str
    recommended_tp_mode: str
    risk_modifier: float


@dataclass
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
    avg_confidence: float


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    txt = str(value).strip().replace("Z", "")
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
    out = str(value or "").strip().lower()
    return out or default


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def infer_setup(row: dict[str, Any]) -> str:
    explicit = norm(row.get("setup_type"), "")
    if explicit:
        return explicit
    text = f"{row.get('kind', '')} {row.get('source', '')}".lower()
    if "pullback" in text:
        return "pullback"
    if "breakout" in text:
        return "breakout"
    if "range" in text or "flat" in text or "reversal" in text:
        return "range_reversal"
    if "ignition" in text or "impulse" in text:
        return "ignition"
    return "unknown"


def infer_trend(row: dict[str, Any]) -> str:
    explicit = norm(row.get("trend_context"), "")
    if explicit:
        if explicit in {"trend", "with_trend", "protrend"}:
            return "trend"
        if explicit in {"countertrend", "against_trend", "counter"}:
            return "countertrend"
        if explicit in {"range", "flat", "neutral", "sideways"}:
            return "range"
        return explicit
    text = f"{row.get('kind', '')} {row.get('source', '')} {row.get('setup_type', '')}".lower()
    if "counter" in text or "against" in text:
        return "countertrend"
    if "trend" in text or "momentum" in text or "ignition" in text:
        return "trend"
    if "flat" in text or "range" in text:
        return "range"
    return "unknown"


def read_trade_rows(path: str | Path) -> list[TradeRow]:
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "side", "entry_time", "entry", "stop", "r_mult"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")
        rows = []
        for row in reader:
            entry_time = parse_dt(row.get("entry_time"))
            if entry_time is None:
                continue
            rows.append(
                TradeRow(
                    symbol=str(row.get("symbol", "")).strip().upper(),
                    side=norm(row.get("side")),
                    entry_time=entry_time,
                    exit_time=parse_dt(row.get("exit_time")),
                    entry=safe_float(row.get("entry")),
                    stop=safe_float(row.get("stop")),
                    exit=safe_float(row.get("exit"), float("nan")),
                    r_mult=safe_float(row.get("r_mult")),
                    kind=str(row.get("kind", "") or "").strip(),
                    source=str(row.get("source", "") or "").strip(),
                    trend_context=infer_trend(row),
                    volatility_regime=norm(row.get("volatility_regime")),
                    setup_type=infer_setup(row),
                )
            )
    return sorted(rows, key=lambda x: (x.entry_time, x.symbol, x.side))


def pf(values: list[float]) -> float:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses <= 0:
        return 99.0 if gains > 0 else 0.0
    return gains / losses


def loss_streak(values: list[float]) -> int:
    best = cur = 0
    for value in values:
        if value < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def symbol_score(history: list[TradeRow], cfg: QualityConfig) -> tuple[float, float, float, float, int]:
    if len(history) < cfg.min_history_trades:
        return 45.0, 0.0, 0.0, 0.0, 0
    vals = [t.r_mult for t in history]
    pfx = pf(vals)
    wr = sum(1 for v in vals if v > 0) / len(vals)
    avg = mean(vals)
    streak = loss_streak(vals)
    score = (clamp(40 + min(len(vals), 20) * 2) * 0.20
             + clamp(45 + (pfx - 1.0) * 22) * 0.30
             + clamp(50 + avg * 35) * 0.25
             + clamp(wr * 100) * 0.25
             - min(streak * 5, 25))
    return clamp(score), pfx, wr, avg, streak


def trend_score(ctx: str) -> float:
    return {"trend": 75.0, "countertrend": 42.0, "range": 60.0, "flat": 60.0, "sideways": 60.0}.get(ctx, 52.0)


def volatility_score(regime: str, stop_risk_pct: float) -> float:
    base = {"good": 70.0, "normal": 70.0, "fit": 70.0, "high": 45.0, "chaotic": 45.0, "bad": 45.0, "low": 50.0, "dead": 50.0}.get(regime, 58.0)
    if stop_risk_pct <= 0:
        risk = 35.0
    elif 0.35 <= stop_risk_pct <= 4.50:
        risk = 75.0
    elif stop_risk_pct <= 8.0:
        risk = 55.0
    else:
        risk = 35.0
    return clamp(base * 0.45 + risk * 0.55)


def target_score(trade: TradeRow, stop_risk_pct: float) -> float:
    base = 55.0
    if trade.trend_context == "trend":
        base += 10
    elif trade.trend_context == "countertrend":
        base -= 8
    elif trade.trend_context in {"range", "flat", "sideways"}:
        base += 2
    if trade.setup_type in {"ignition", "breakout"} and trade.trend_context == "trend":
        base += 5
    if trade.setup_type == "pullback" and trade.trend_context in {"trend", "range"}:
        base += 3
    if stop_risk_pct > 8:
        base -= 15
    elif 0 < stop_risk_pct < 0.35:
        base -= 8
    return clamp(base)


def entry_score(setup: str, stop_risk_pct: float) -> float:
    base = {"pullback": 62.0, "range_reversal": 60.0, "ignition": 66.0, "breakout": 58.0}.get(setup, 52.0)
    if 0.35 <= stop_risk_pct <= 4.50:
        base += 10
    elif stop_risk_pct > 8:
        base -= 15
    elif stop_risk_pct <= 0:
        base -= 20
    return clamp(base)


def decision(score: float, cfg: QualityConfig) -> str:
    if score >= cfg.take_threshold:
        return "TAKE"
    if score >= cfg.watch_threshold:
        return "WATCH"
    return "SKIP"


def tp_mode(trade: TradeRow, conf: float) -> str:
    if trade.trend_context == "trend" and conf >= 65:
        return "wider_trend_tp"
    if trade.trend_context == "countertrend":
        return "compressed_countertrend_tp"
    if conf < 50:
        return "no_trade"
    return "normal_tp"


def risk_mod(score: float, cfg: QualityConfig) -> float:
    if score >= 75:
        return 1.0
    if score >= cfg.take_threshold:
        return 0.8
    if score >= cfg.watch_threshold:
        return 0.5
    return 0.0


def score_trades(trades: list[TradeRow], cfg: QualityConfig | None = None) -> list[ScoredTrade]:
    cfg = cfg or QualityConfig()
    out = []
    for trade in trades:
        start = trade.entry_time - timedelta(days=cfg.lookback_days)
        history = [t for t in trades if t.symbol == trade.symbol and start <= t.entry_time < trade.entry_time]
        ss, hp, hw, ha, hs = symbol_score(history, cfg)
        stop_pct = abs(trade.entry - trade.stop) / trade.entry * 100 if trade.entry > 0 else 0.0
        ts = trend_score(trade.trend_context)
        vs = volatility_score(trade.volatility_regime, stop_pct)
        trs = target_score(trade, stop_pct)
        es = entry_score(trade.setup_type, stop_pct)
        conf = clamp(ss * 0.35 + ts * 0.20 + vs * 0.15 + trs * 0.15 + es * 0.15)
        out.append(ScoredTrade(
            trade.symbol, trade.side, trade.entry_time.isoformat(), trade.exit_time.isoformat() if trade.exit_time else "",
            trade.kind, trade.source, trade.setup_type, trade.trend_context, trade.volatility_regime,
            round(trade.r_mult, 6), "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat",
            round(stop_pct, 4), len(history), round(hp, 4), round(hw, 4), round(ha, 4), hs,
            round(ss, 2), round(ts, 2), round(vs, 2), round(trs, 2), round(es, 2), round(conf, 2),
            decision(conf, cfg), tp_mode(trade, conf), risk_mod(conf, cfg)))
    return out


def summarize(rows: list[ScoredTrade], group: str, value: str) -> BreakdownRow:
    vals = [r.r_mult for r in rows]
    wins = sum(1 for v in vals if v > 0)
    losses = sum(1 for v in vals if v < 0)
    return BreakdownRow(group, value, len(rows), wins, losses,
                        round(wins / len(rows), 4) if rows else 0.0,
                        round(mean(vals), 4) if vals else 0.0,
                        round(pf(vals), 4), round(sum(vals), 4),
                        round(mean([r.trade_confidence_score for r in rows]), 2) if rows else 0.0)


def build_breakdown(scored: list[ScoredTrade]) -> list[BreakdownRow]:
    groups: dict[str, dict[str, list[ScoredTrade]]] = {"side": {}, "trend_context": {}, "setup_type": {}, "decision": {}, "symbol": {}}
    for row in scored:
        for group, value in [("side", row.side), ("trend_context", row.trend_context), ("setup_type", row.setup_type), ("decision", row.decision), ("symbol", row.symbol)]:
            groups[group].setdefault(value, []).append(row)
    return [summarize(rows, group, value) for group, values in groups.items() for value, rows in sorted(values.items())]


def summary(scored: list[ScoredTrade], cfg: QualityConfig) -> dict[str, Any]:
    vals = [r.r_mult for r in scored]
    take = [r for r in scored if r.decision == "TAKE"]
    watch = [r for r in scored if r.decision == "WATCH"]
    skip = [r for r in scored if r.decision == "SKIP"]
    return {
        "lookback_days": cfg.lookback_days,
        "min_history_trades": cfg.min_history_trades,
        "take_threshold": cfg.take_threshold,
        "watch_threshold": cfg.watch_threshold,
        "trades": len(scored),
        "winrate": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else 0.0,
        "avg_r": round(mean(vals), 4) if vals else 0.0,
        "total_r": round(sum(vals), 4),
        "pf": round(pf(vals), 4),
        "avg_confidence": round(mean([r.trade_confidence_score for r in scored]), 2) if scored else 0.0,
        "take_trades": len(take),
        "take_avg_r": round(mean([r.r_mult for r in take]), 4) if take else 0.0,
        "take_pf": round(pf([r.r_mult for r in take]), 4),
        "watch_trades": len(watch),
        "watch_avg_r": round(mean([r.r_mult for r in watch]), 4) if watch else 0.0,
        "skip_trades": len(skip),
        "skip_avg_r": round(mean([r.r_mult for r in skip]), 4) if skip else 0.0,
    }


def write_csv(path: str | Path, rows: list[Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_summary(path: str | Path, row: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def run_quality_report(input_csv: str | Path, out_dir: str | Path = "results", cfg: QualityConfig | None = None) -> dict[str, Any]:
    cfg = cfg or QualityConfig()
    out_dir = Path(out_dir)
    scored = score_trades(read_trade_rows(input_csv), cfg)
    report = summary(scored, cfg)
    write_csv(out_dir / "trade_quality_scored_trades.csv", scored)
    write_csv(out_dir / "trade_quality_breakdown.csv", build_breakdown(scored))
    write_summary(out_dir / "trade_quality_summary.csv", report)
    return report
