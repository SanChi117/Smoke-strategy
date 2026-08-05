#!/usr/bin/env python3
"""Hardening wrapper for the unified SMOKE paper control server.

The base server remains readable and stable. This wrapper applies the two
stateful rules required to match the validated research pipeline:

1. adaptive Quality/Structure history is seeded from every generated candidate;
2. every live raw candidate is tracked as a shadow trade until TP/SL/time-stop,
   even when the final Decision Engine blocks the paper entry.

Paper/research only. No exchange orders.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import smoke_control_server as core  # noqa: E402
from strategy_lab.decision_engine import DecisionResult, HistoricalTrade, LayerResult  # noqa: E402


HISTORY_SEED_VERSION = "all_candidates_v2"
ORIGINAL_INIT_SCHEMA = core.init_schema
ORIGINAL_SAVE_DECISION = core.save_decision
ORIGINAL_MONITOR_OPEN_TRADES = core.monitor_open_trades
ORIGINAL_EVALUATE_CANDIDATE = core.evaluate_candidate
ORIGINAL_STATUS_PAYLOAD = core.status_payload


def init_schema() -> None:
    ORIGINAL_INIT_SCHEMA()
    with core.DB_LOCK, core.connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS shadow_trades (
                shadow_trade_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                expiry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                target_rr REAL NOT NULL,
                setup_type TEXT NOT NULL,
                trend_context TEXT DEFAULT '',
                volatility_regime TEXT DEFAULT '',
                structure_type TEXT DEFAULT '',
                status TEXT NOT NULL,
                exit_time TEXT DEFAULT '',
                exit_price REAL DEFAULT 0,
                exit_reason TEXT DEFAULT '',
                result_r REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_shadow_status
            ON shadow_trades(status, entry_time DESC);
            """
        )
        conn.commit()


def historical_trades() -> list[HistoricalTrade]:
    """Return outcomes of all closed raw candidates, never paper-only history."""
    with core.DB_LOCK, core.connect_db() as conn:
        rows = [core.row_dict(row) for row in conn.execute("SELECT * FROM history_trades ORDER BY exit_time ASC")]
    return [
        HistoricalTrade(
            symbol=row["symbol"],
            side=row["side"],
            entry_time=core.parse_dt(row["entry_time"]),
            exit_time=core.parse_dt(row["exit_time"]),
            entry=float(row["entry_price"]),
            stop=float(row["stop_price"]),
            exit=float(row["exit_price"]),
            r_mult=float(row["result_r"]),
            setup_type=row["setup_type"],
            trend_context=row["trend_context"],
            volatility_regime=row["volatility_regime"],
            structure_type=row["structure_type"],
            source=row["source"],
        )
        for row in rows
    ]


def bootstrap_history_if_needed(universe: list[str]) -> int:
    """Seed learning with every historical generated candidate outcome."""
    current_version = core.setting_get("history_seed_version", "")
    with core.DB_LOCK, core.connect_db() as conn:
        if current_version != HISTORY_SEED_VERSION:
            conn.execute("DELETE FROM history_trades WHERE source='causal_bootstrap'")
            conn.commit()
        existing = int(conn.execute("SELECT COUNT(*) AS n FROM history_trades WHERE source='causal_bootstrap'").fetchone()["n"])
    if existing > 0 and current_version == HISTORY_SEED_VERSION:
        return existing
    if not core.SETTINGS.auto_bootstrap_history:
        return 0

    candles = core.STORE.all_candles(universe, core.SETTINGS.interval, core.SETTINGS.history_bars)
    if len(candles) < max(300, len(universe) * 60):
        core.log_event("WARN", "not enough candles to seed adaptive history", {"candles": len(candles)})
        return 0

    work = core.SETTINGS.runtime_dir / "history_seed_v2"
    work.mkdir(parents=True, exist_ok=True)
    candles_csv = work / "candles.csv"
    core.write_candles_csv(candles_csv, candles)
    core.log_event("INFO", "building all-candidate causal history seed", {"candles": len(candles), "symbols": len(universe)})
    core.run_end_to_end_pipeline(
        candles_csv,
        work / "pipeline",
        "growth_100_20x",
        43.0,
        core.baseline_pipeline_config(),
    )
    generated_csv = work / "pipeline" / "generated_trades.csv"
    if not generated_csv.exists() or generated_csv.stat().st_size == 0:
        core.log_event("WARN", "history seed produced no generated candidates")
        return 0

    inserted = 0
    with generated_csv.open("r", newline="", encoding="utf-8") as handle, core.DB_LOCK, core.connect_db() as conn:
        for row in csv.DictReader(handle):
            if str(row.get("exit_reason", "")) == "no_future_candles":
                continue
            if not row.get("exit_time"):
                continue
            history_id = f"seed|{row.get('symbol')}|{row.get('side')}|{row.get('entry_time')}"
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO history_trades(
                    history_id, symbol, side, entry_time, exit_time, entry_price,
                    stop_price, exit_price, result_r, setup_type, trend_context,
                    volatility_regime, structure_type, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'causal_bootstrap')
                """,
                (
                    history_id,
                    row.get("symbol", ""),
                    row.get("side", ""),
                    row.get("entry_time", ""),
                    row.get("exit_time", ""),
                    float(row.get("entry", 0) or 0),
                    float(row.get("stop", 0) or 0),
                    float(row.get("exit", 0) or 0),
                    float(row.get("r_mult", 0) or 0),
                    row.get("setup_type", row.get("kind", "")),
                    row.get("trend_context", ""),
                    row.get("volatility_regime", ""),
                    row.get("structure_type", ""),
                ),
            )
            inserted += int(conn.total_changes > before)
        conn.commit()
    core.setting_set("history_seed_version", HISTORY_SEED_VERSION)
    core.log_event("INFO", "all-candidate causal history ready", {"trades": inserted})
    return inserted


def open_shadow_trade(plan: Any) -> bool:
    shadow_id = f"shadow|{core.candidate_key(plan)}"
    now = core.iso_now()
    with core.DB_LOCK, core.connect_db() as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO shadow_trades(
                shadow_trade_id, project_id, symbol, side, entry_time, expiry_time,
                entry_price, stop_price, target_price, target_rr, setup_type,
                trend_context, volatility_regime, structure_type, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                shadow_id,
                core.SETTINGS.project_id,
                str(plan.symbol).upper(),
                str(plan.side).lower(),
                core.parse_dt(plan.entry_time).isoformat(timespec="seconds"),
                core.parse_dt(plan.exit_time).isoformat(timespec="seconds"),
                float(plan.entry),
                float(plan.stop),
                float(plan.target),
                float(plan.target_rr),
                str(plan.setup_type),
                str(plan.trend_context),
                str(plan.volatility_regime),
                str(plan.structure_type),
                now,
                now,
            ),
        )
        conn.commit()
        return conn.total_changes > before


def save_decision(plan: Any, decision: Any) -> None:
    ORIGINAL_SAVE_DECISION(plan, decision)
    open_shadow_trade(plan)


def close_shadow_trade(row: dict[str, Any], exit_time: datetime, exit_price: float, reason: str) -> None:
    entry = float(row["entry_price"])
    stop = float(row["stop_price"])
    risk = abs(entry - stop) or 1e-12
    result_r = (entry - exit_price) / risk if row["side"] == "short" else (exit_price - entry) / risk
    now = core.iso_now()
    history_id = f"live|{row['shadow_trade_id']}"
    with core.DB_LOCK, core.connect_db() as conn:
        conn.execute(
            """
            UPDATE shadow_trades
            SET status='closed', exit_time=?, exit_price=?, exit_reason=?, result_r=?, updated_at=?
            WHERE shadow_trade_id=? AND status='open'
            """,
            (exit_time.isoformat(timespec="seconds"), round(exit_price, 8), reason, round(result_r, 6), now, row["shadow_trade_id"]),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO history_trades(
                history_id, symbol, side, entry_time, exit_time, entry_price,
                stop_price, exit_price, result_r, setup_type, trend_context,
                volatility_regime, structure_type, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live_shadow')
            """,
            (
                history_id,
                row["symbol"],
                row["side"],
                row["entry_time"],
                exit_time.isoformat(timespec="seconds"),
                entry,
                stop,
                round(exit_price, 8),
                round(result_r, 6),
                row["setup_type"],
                row["trend_context"],
                row["volatility_regime"],
                row["structure_type"],
            ),
        )
        conn.commit()


def monitor_shadow_trades() -> int:
    with core.DB_LOCK, core.connect_db() as conn:
        rows = [core.row_dict(row) for row in conn.execute("SELECT * FROM shadow_trades WHERE status='open' ORDER BY entry_time ASC")]
    closed = 0
    for row in rows:
        entry_time = core.parse_dt(row["entry_time"])
        expiry_time = core.parse_dt(row["expiry_time"])
        stop = float(row["stop_price"])
        target = float(row["target_price"])
        for candle in core.STORE.candles(row["symbol"], core.SETTINGS.interval, core.SETTINGS.history_bars):
            if candle.time <= entry_time:
                continue
            if row["side"] == "short":
                if candle.high >= stop:
                    close_shadow_trade(row, candle.time, stop, "stop_loss")
                    closed += 1
                    break
                if candle.low <= target:
                    close_shadow_trade(row, candle.time, target, "take_profit")
                    closed += 1
                    break
            else:
                if candle.low <= stop:
                    close_shadow_trade(row, candle.time, stop, "stop_loss")
                    closed += 1
                    break
                if candle.high >= target:
                    close_shadow_trade(row, candle.time, target, "take_profit")
                    closed += 1
                    break
            if candle.time >= expiry_time:
                close_shadow_trade(row, candle.time, candle.close, "time_stop")
                closed += 1
                break
    return closed


def monitor_open_trades() -> int:
    return ORIGINAL_MONITOR_OPEN_TRADES() + monitor_shadow_trades()


def open_total_count() -> int:
    with core.DB_LOCK, core.connect_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM paper_trades WHERE status='open'").fetchone()
    return int(row["n"] if row else 0)


def evaluate_candidate(*args: Any, **kwargs: Any) -> DecisionResult:
    result = ORIGINAL_EVALUATE_CANDIDATE(*args, **kwargs)
    max_total = max(1, int(os.environ.get("SMOKE_MAX_OPEN_TOTAL", "2")))
    if not result.ready or open_total_count() < max_total:
        return result
    layers = tuple(
        LayerResult("PORTFOLIO", "BLOCK", "max_open_total", {"total_open": open_total_count(), "max": max_total})
        if layer.layer == "PORTFOLIO"
        else layer
        for layer in result.layers
    )
    return DecisionResult(
        baseline=result.baseline,
        symbol=result.symbol,
        side=result.side,
        entry_time=result.entry_time,
        final_status="BLOCKED",
        ready=False,
        quality_decision=result.quality_decision,
        structure_decision=result.structure_decision,
        layers=layers,
    )


def status_payload() -> dict[str, Any]:
    payload = ORIGINAL_STATUS_PAYLOAD()
    with core.DB_LOCK, core.connect_db() as conn:
        payload["open_shadow_trades"] = int(conn.execute("SELECT COUNT(*) AS n FROM shadow_trades WHERE status='open'").fetchone()["n"])
        payload["closed_shadow_trades"] = int(conn.execute("SELECT COUNT(*) AS n FROM shadow_trades WHERE status='closed'").fetchone()["n"])
    return payload


def apply_patches() -> None:
    core.init_schema = init_schema
    core.historical_trades = historical_trades
    core.bootstrap_history_if_needed = bootstrap_history_if_needed
    core.save_decision = save_decision
    core.monitor_open_trades = monitor_open_trades
    core.evaluate_candidate = evaluate_candidate
    core.status_payload = status_payload


def main() -> int:
    apply_patches()
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
