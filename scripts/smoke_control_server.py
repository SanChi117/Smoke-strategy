#!/usr/bin/env python3
"""SMOKE paper control server.

One always-on process provides:
- incremental closed-candle ingestion from public Binance Futures;
- the validated layered Decision Engine;
- virtual paper trade lifecycle and causal adaptive history;
- SQLite persistence;
- a small web control panel and JSON API.

Paper/research only. No API keys. No real orders.
"""

from __future__ import annotations

import base64
import csv
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy_lab.config import PipelineConfig  # noqa: E402
from strategy_lab.decision_engine import BASELINE_NAME, DecisionEngineConfig, HistoricalTrade, evaluate_candidate  # noqa: E402
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline  # noqa: E402
from strategy_lab.live_market import CandleStore, fetch_active_usdt_perpetual_symbols, sync_symbol, validate_universe  # noqa: E402
from strategy_lab.market_data import Candle, group_candles_by_symbol, write_candles_csv  # noqa: E402
from strategy_lab.mtf_feature_builder import build_features  # noqa: E402
from strategy_lab.risk_model import RiskPlan, build_risk_plans  # noqa: E402
from strategy_lab.setup_generator import generate_candidate_setups  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "").replace("T", " "))


def read_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Settings:
    def __init__(self) -> None:
        env_path = Path(os.environ.get("SMOKE_ENV_FILE", ROOT / ".env.smoke"))
        read_env_file(env_path)
        self.project_id = os.environ.get("SMOKE_PROJECT_ID", "smoke")
        self.project_name = os.environ.get("SMOKE_PROJECT_NAME", "SMOKE Strategy")
        self.host = os.environ.get("SMOKE_HOST", "127.0.0.1")
        self.port = int(os.environ.get("SMOKE_PORT", "8095"))
        self.admin_user = os.environ.get("SMOKE_ADMIN_USER", "smoke")
        self.admin_password = os.environ.get("SMOKE_ADMIN_PASSWORD", "")
        self.api_secret = os.environ.get("SMOKE_API_SECRET", "")
        self.runtime_dir = Path(os.environ.get("SMOKE_RUNTIME_DIR", ROOT / "runtime" / "smoke_control"))
        self.db_path = Path(os.environ.get("SMOKE_DB_PATH", self.runtime_dir / "smoke.sqlite3"))
        self.interval = os.environ.get("SMOKE_INTERVAL", "15m")
        self.bootstrap_limit = int(os.environ.get("SMOKE_BOOTSTRAP_LIMIT", "1200"))
        self.history_bars = int(os.environ.get("SMOKE_HISTORY_BARS", "1200"))
        self.poll_seconds = max(20, int(os.environ.get("SMOKE_POLL_SECONDS", "30")))
        self.symbol_sleep_seconds = max(0.0, float(os.environ.get("SMOKE_SYMBOL_SLEEP_SECONDS", "0.03")))
        self.auto_scan = parse_bool(os.environ.get("SMOKE_AUTO_SCAN"), True)
        self.auto_bootstrap_history = parse_bool(os.environ.get("SMOKE_AUTO_BOOTSTRAP_HISTORY"), True)
        self.max_symbols = max(1, int(os.environ.get("SMOKE_MAX_SYMBOLS", "150")))
        self.symbols_file = Path(os.environ.get("SMOKE_SYMBOLS_FILE", ROOT / "results" / "strategy_universe_layer" / "combined_symbols.txt"))
        self.symbols_fallback = os.environ.get("SMOKE_SYMBOLS", "INJUSDT,TONUSDT,DOGEUSDT,ARBUSDT,NEARUSDT,OPUSDT")
        self.daily_dd_stop_pct = float(os.environ.get("SMOKE_DAILY_DD_STOP_PCT", "2.0"))
        self.weekly_dd_stop_pct = float(os.environ.get("SMOKE_WEEKLY_DD_STOP_PCT", "5.0"))
        self.max_stop_streak = int(os.environ.get("SMOKE_MAX_STOP_STREAK", "3"))
        self.max_open_per_symbol = int(os.environ.get("SMOKE_MAX_OPEN_PER_SYMBOL", "1"))
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def requested_symbols(self) -> list[str]:
        text = self.symbols_file.read_text(encoding="utf-8") if self.symbols_file.exists() else self.symbols_fallback
        values = [part.strip().upper().replace("/", "").replace("_", "") for part in text.replace("\n", ",").split(",") if part.strip()]
        return list(dict.fromkeys(values))[: self.max_symbols]


SETTINGS = Settings()
DB_LOCK = threading.RLock()
SCAN_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
STATE: dict[str, Any] = {
    "paused": not SETTINGS.auto_scan,
    "scan_running": False,
    "last_scan_started": "",
    "last_scan_finished": "",
    "last_scan_status": "never",
    "last_error": "",
    "universe": [],
    "last_completed_bucket": "",
}
STORE = CandleStore(SETTINGS.db_path)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(SETTINGS.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema() -> None:
    with DB_LOCK, connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT DEFAULT '',
                status TEXT NOT NULL,
                symbols INTEGER DEFAULT 0,
                candles_synced INTEGER DEFAULT 0,
                candidates INTEGER DEFAULT 0,
                ready INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                opened INTEGER DEFAULT 0,
                closed INTEGER DEFAULT 0,
                error TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_key TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                baseline TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                target_rr REAL NOT NULL,
                setup_type TEXT NOT NULL,
                final_status TEXT NOT NULL,
                quality_decision TEXT DEFAULT '',
                structure_decision TEXT DEFAULT '',
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS layer_results (
                candidate_key TEXT NOT NULL,
                layer TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                value_json TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(candidate_key, layer)
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                paper_trade_id TEXT PRIMARY KEY,
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
                result_pct REAL DEFAULT 0,
                source TEXT DEFAULT 'paper_live',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history_trades (
                history_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                result_r REAL NOT NULL,
                setup_type TEXT NOT NULL,
                trend_context TEXT DEFAULT '',
                volatility_regime TEXT DEFAULT '',
                structure_type TEXT DEFAULT '',
                source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_candidates_time ON candidates(entry_time DESC);
            CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status, entry_time DESC);
            CREATE INDEX IF NOT EXISTS idx_events_time ON system_events(event_time DESC);
            """
        )
        conn.commit()


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def log_event(level: str, message: str, payload: Any | None = None) -> None:
    text = "" if payload is None else json.dumps(payload, ensure_ascii=False, default=str)
    with DB_LOCK, connect_db() as conn:
        conn.execute("INSERT INTO system_events(event_time, level, message, payload_json) VALUES (?, ?, ?, ?)", (iso_now(), level, message, text))
        conn.commit()
    print(f"[{level}] {message} {text}")


def setting_get(key: str, default: str = "") -> str:
    with DB_LOCK, connect_db() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def setting_set(key: str, value: Any) -> None:
    with DB_LOCK, connect_db() as conn:
        conn.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), iso_now()),
        )
        conn.commit()


def refresh_universe() -> list[str]:
    requested = SETTINGS.requested_symbols()
    try:
        universe = validate_universe(requested, fetch_active_usdt_perpetual_symbols())
    except Exception as exc:
        log_event("WARN", "universe validation failed; keeping requested list", {"error": repr(exc)})
        universe = requested
    if not universe:
        raise RuntimeError("No active symbols in universe")
    with STATE_LOCK:
        STATE["universe"] = universe
    log_event("INFO", "universe ready", {"requested": len(requested), "active": len(universe)})
    return universe


def kill_status() -> dict[str, Any]:
    now = utc_now()
    today = now.date().isoformat()
    week_start = (now.date() - timedelta(days=now.weekday())).isoformat()
    with DB_LOCK, connect_db() as conn:
        rows = [row_dict(row) for row in conn.execute("SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_time ASC")]
    daily = sum(float(row["result_pct"] or 0) for row in rows if str(row["exit_time"])[:10] == today)
    weekly = sum(float(row["result_pct"] or 0) for row in rows if str(row["exit_time"])[:10] >= week_start)
    streak = 0
    for row in reversed(rows):
        if row["exit_reason"] == "stop_loss":
            streak += 1
        else:
            break
    reasons: list[str] = []
    if daily <= -abs(SETTINGS.daily_dd_stop_pct):
        reasons.append("daily_drawdown_stop")
    if weekly <= -abs(SETTINGS.weekly_dd_stop_pct):
        reasons.append("weekly_drawdown_stop")
    if streak >= SETTINGS.max_stop_streak:
        reasons.append("stop_loss_streak")
    return {"blocked": bool(reasons), "reasons": reasons, "daily_result_pct": round(daily, 6), "weekly_result_pct": round(weekly, 6), "consecutive_stop_losses": streak}


def open_symbol_count(symbol: str) -> int:
    with DB_LOCK, connect_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM paper_trades WHERE status='open' AND symbol=?", (symbol.upper(),)).fetchone()
    return int(row["n"] if row else 0)


def historical_trades() -> list[HistoricalTrade]:
    with DB_LOCK, connect_db() as conn:
        history_rows = [row_dict(row) for row in conn.execute("SELECT * FROM history_trades ORDER BY exit_time ASC")]
        paper_rows = [row_dict(row) for row in conn.execute("SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_time ASC")]
    out: list[HistoricalTrade] = []
    for row in history_rows:
        out.append(HistoricalTrade(row["symbol"], row["side"], parse_dt(row["entry_time"]), parse_dt(row["exit_time"]), float(row["entry_price"]), float(row["stop_price"]), float(row["exit_price"]), float(row["result_r"]), row["setup_type"], row["trend_context"], row["volatility_regime"], row["structure_type"], source=row["source"]))
    for row in paper_rows:
        out.append(HistoricalTrade(row["symbol"], row["side"], parse_dt(row["entry_time"]), parse_dt(row["exit_time"]), float(row["entry_price"]), float(row["stop_price"]), float(row["exit_price"]), float(row["result_r"]), row["setup_type"], row["trend_context"], row["volatility_regime"], row["structure_type"], source=row["source"]))
    return sorted(out, key=lambda trade: (trade.exit_time, trade.symbol, trade.side))


def baseline_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        name=BASELINE_NAME,
        require_rolling_top=False,
        require_universe_gate=False,
        quality_take_threshold=66.0,
        quality_watch_threshold=54.0,
        structure_take_threshold=64.0,
        structure_watch_threshold=54.0,
        allowed_setup_types=("pullback", "ignition"),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        blocked_volatility_regimes=("high",),
        blocked_liquidity_states=("high_sweep_reject",),
        blocked_candle_types=("bear_rejection",),
        allowed_direction_contexts=("down",),
        min_volume_ratio=0.70,
    )


def bootstrap_history_if_needed(universe: list[str]) -> int:
    if not SETTINGS.auto_bootstrap_history:
        return 0
    with DB_LOCK, connect_db() as conn:
        count = int(conn.execute("SELECT COUNT(*) AS n FROM history_trades").fetchone()["n"])
    if count > 0:
        return count
    candles = STORE.all_candles(universe, SETTINGS.interval, SETTINGS.history_bars)
    if len(candles) < max(300, len(universe) * 60):
        log_event("WARN", "not enough candles to seed adaptive history", {"candles": len(candles)})
        return 0
    work = SETTINGS.runtime_dir / "history_seed"
    work.mkdir(parents=True, exist_ok=True)
    candles_csv = work / "candles.csv"
    write_candles_csv(candles_csv, candles)
    log_event("INFO", "building causal history seed", {"candles": len(candles), "symbols": len(universe)})
    run_end_to_end_pipeline(candles_csv, work / "pipeline", "growth_100_20x", 43.0, baseline_pipeline_config())
    allowed_csv = work / "pipeline" / "pipeline_allowed_trades.csv"
    if not allowed_csv.exists() or allowed_csv.stat().st_size == 0:
        log_event("WARN", "history seed produced no allowed trades")
        return 0
    inserted = 0
    with allowed_csv.open("r", newline="", encoding="utf-8") as f, DB_LOCK, connect_db() as conn:
        for row in csv.DictReader(f):
            history_id = f"seed|{row.get('symbol')}|{row.get('side')}|{row.get('entry_time')}"
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO history_trades(
                    history_id, symbol, side, entry_time, exit_time, entry_price, stop_price, exit_price,
                    result_r, setup_type, trend_context, volatility_regime, structure_type, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (history_id, row.get("symbol", ""), row.get("side", ""), row.get("entry_time", ""), row.get("exit_time", ""), float(row.get("entry", 0) or 0), float(row.get("stop", 0) or 0), float(row.get("exit", 0) or 0), float(row.get("r_mult", 0) or 0), row.get("setup_type", row.get("kind", "")), row.get("trend_context", ""), row.get("volatility_regime", ""), row.get("structure_type", ""), "causal_bootstrap"),
            )
            inserted += int(conn.total_changes > before)
        conn.commit()
    log_event("INFO", "causal history seed ready", {"trades": inserted})
    return inserted


def candidate_key(plan: RiskPlan) -> str:
    return f"{BASELINE_NAME}|{plan.symbol.upper()}|{plan.side.lower()}|{parse_dt(plan.entry_time).isoformat(timespec='seconds')}"


def save_decision(plan: RiskPlan, decision: Any) -> None:
    key = candidate_key(plan)
    now = iso_now()
    with DB_LOCK, connect_db() as conn:
        conn.execute(
            """
            INSERT INTO candidates(candidate_key, project_id, baseline, symbol, side, entry_time, entry_price, stop_price, target_price, target_rr, setup_type, final_status, quality_decision, structure_decision, decision_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_key) DO UPDATE SET final_status=excluded.final_status, quality_decision=excluded.quality_decision, structure_decision=excluded.structure_decision, decision_json=excluded.decision_json, updated_at=excluded.updated_at
            """,
            (key, SETTINGS.project_id, BASELINE_NAME, plan.symbol.upper(), plan.side.lower(), parse_dt(plan.entry_time).isoformat(timespec="seconds"), float(plan.entry), float(plan.stop), float(plan.target), float(plan.target_rr), plan.setup_type, decision.final_status, decision.quality_decision, decision.structure_decision, json.dumps(decision.as_dict(), ensure_ascii=False, default=str), now, now),
        )
        for layer in decision.layers:
            conn.execute(
                """
                INSERT INTO layer_results(candidate_key, layer, status, reason, value_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_key, layer) DO UPDATE SET status=excluded.status, reason=excluded.reason, value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, layer.layer, layer.status, layer.reason, json.dumps(layer.value, ensure_ascii=False, default=str), now),
            )
        conn.commit()


def open_paper_trade(plan: RiskPlan, decision: Any) -> bool:
    if not decision.ready or open_symbol_count(plan.symbol) >= SETTINGS.max_open_per_symbol or kill_status()["blocked"]:
        return False
    paper_id = f"paper|{candidate_key(plan)}"
    now = iso_now()
    with DB_LOCK, connect_db() as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_trades(paper_trade_id, project_id, symbol, side, entry_time, expiry_time, entry_price, stop_price, target_price, target_rr, setup_type, trend_context, volatility_regime, structure_type, status, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 'paper_live', ?, ?)
            """,
            (paper_id, SETTINGS.project_id, plan.symbol.upper(), plan.side.lower(), parse_dt(plan.entry_time).isoformat(timespec="seconds"), parse_dt(plan.exit_time).isoformat(timespec="seconds"), float(plan.entry), float(plan.stop), float(plan.target), float(plan.target_rr), plan.setup_type, plan.trend_context, plan.volatility_regime, plan.structure_type, now, now),
        )
        conn.commit()
        opened = conn.total_changes > before
    if opened:
        log_event("INFO", "paper trade opened", {"paper_trade_id": paper_id, "symbol": plan.symbol, "side": plan.side})
    return opened


def close_paper_trade(row: dict[str, Any], exit_time: datetime, exit_price: float, reason: str) -> None:
    entry = float(row["entry_price"])
    stop = float(row["stop_price"])
    risk = abs(entry - stop) or 1e-12
    result_r = (entry - exit_price) / risk if row["side"] == "short" else (exit_price - entry) / risk
    result_pct = (entry - exit_price) / entry * 100.0 if row["side"] == "short" else (exit_price - entry) / entry * 100.0
    with DB_LOCK, connect_db() as conn:
        conn.execute("UPDATE paper_trades SET status='closed', exit_time=?, exit_price=?, exit_reason=?, result_r=?, result_pct=?, updated_at=? WHERE paper_trade_id=? AND status='open'", (exit_time.isoformat(timespec="seconds"), round(exit_price, 8), reason, round(result_r, 6), round(result_pct, 6), iso_now(), row["paper_trade_id"]))
        conn.commit()
    log_event("INFO", "paper trade closed", {"paper_trade_id": row["paper_trade_id"], "reason": reason, "result_r": round(result_r, 4)})


def monitor_open_trades() -> int:
    with DB_LOCK, connect_db() as conn:
        open_rows = [row_dict(row) for row in conn.execute("SELECT * FROM paper_trades WHERE status='open' ORDER BY entry_time ASC")]
    closed = 0
    for row in open_rows:
        entry_time = parse_dt(row["entry_time"])
        expiry_time = parse_dt(row["expiry_time"])
        stop = float(row["stop_price"])
        target = float(row["target_price"])
        for candle in STORE.candles(row["symbol"], SETTINGS.interval, SETTINGS.history_bars):
            if candle.time <= entry_time:
                continue
            if row["side"] == "short":
                if candle.high >= stop:
                    close_paper_trade(row, candle.time, stop, "stop_loss"); closed += 1; break
                if candle.low <= target:
                    close_paper_trade(row, candle.time, target, "take_profit"); closed += 1; break
            else:
                if candle.low <= stop:
                    close_paper_trade(row, candle.time, stop, "stop_loss"); closed += 1; break
                if candle.high >= target:
                    close_paper_trade(row, candle.time, target, "take_profit"); closed += 1; break
            if candle.time >= expiry_time:
                close_paper_trade(row, candle.time, candle.close, "time_stop"); closed += 1; break
    return closed


def data_fresh_for(candle: Candle) -> bool:
    age = (utc_now() - (candle.time + timedelta(minutes=15))).total_seconds()
    return -5 <= age <= 20 * 60


def execute_scan(trigger: str = "auto") -> dict[str, Any]:
    if not SCAN_LOCK.acquire(blocking=False):
        return {"ok": False, "reason": "scan_already_running"}
    with STATE_LOCK:
        STATE.update({"scan_running": True, "last_scan_started": iso_now(), "last_scan_status": "running"})
    started = iso_now()
    with DB_LOCK, connect_db() as conn:
        run_id = conn.execute("INSERT INTO scan_runs(started_at, status) VALUES (?, 'running')", (started,)).lastrowid
        conn.commit()
    try:
        universe = list(STATE.get("universe") or refresh_universe())
        synced = 0
        for symbol in universe:
            synced += int(sync_symbol(STORE, symbol, SETTINGS.interval, SETTINGS.bootstrap_limit).stored)
            if SETTINGS.symbol_sleep_seconds:
                time.sleep(SETTINGS.symbol_sleep_seconds)
        bootstrap_history_if_needed(universe)
        closed = monitor_open_trades()
        candles = STORE.all_candles(universe, SETTINGS.interval, SETTINGS.history_bars)
        by_symbol = group_candles_by_symbol(candles)
        plans = build_risk_plans(generate_candidate_setups(build_features(candles), min_confidence=43.0))
        latest_by_symbol = {symbol: rows[-1].time for symbol, rows in by_symbol.items() if rows}
        current_plans = [plan for plan in plans if latest_by_symbol.get(plan.symbol) == parse_dt(plan.entry_time)]
        history = historical_trades()
        ks = kill_status()
        ready = blocked = opened = 0
        engine_cfg = DecisionEngineConfig(max_open_per_symbol=SETTINGS.max_open_per_symbol, cold_start_policy="block")
        for plan in current_plans:
            decision = evaluate_candidate(plan, history, data_fresh=data_fresh_for(by_symbol[plan.symbol][-1]), candle_closed=True, universe_allowed=plan.symbol in universe, open_symbol_positions=open_symbol_count(plan.symbol), kill_switch_blocked=bool(ks["blocked"]), cfg=engine_cfg)
            save_decision(plan, decision)
            if decision.ready:
                ready += 1
                opened += int(open_paper_trade(plan, decision))
            else:
                blocked += 1
        result = {"ok": True, "trigger": trigger, "symbols": len(universe), "candles_synced": synced, "candles_total": len(candles), "candidates": len(current_plans), "ready": ready, "blocked": blocked, "opened": opened, "closed": closed}
        finished = iso_now()
        with DB_LOCK, connect_db() as conn:
            conn.execute("UPDATE scan_runs SET finished_at=?, status='ok', symbols=?, candles_synced=?, candidates=?, ready=?, blocked=?, opened=?, closed=? WHERE id=?", (finished, len(universe), synced, len(current_plans), ready, blocked, opened, closed, run_id))
            conn.commit()
        with STATE_LOCK:
            STATE.update({"last_scan_finished": finished, "last_scan_status": "ok", "last_error": ""})
        log_event("INFO", "scan complete", result)
        return result
    except Exception as exc:
        error = repr(exc)
        finished = iso_now()
        with DB_LOCK, connect_db() as conn:
            conn.execute("UPDATE scan_runs SET finished_at=?, status='error', error=? WHERE id=?", (finished, error, run_id)); conn.commit()
        with STATE_LOCK:
            STATE.update({"last_scan_finished": finished, "last_scan_status": "error", "last_error": error})
        log_event("ERROR", "scan failed", {"error": error})
        return {"ok": False, "error": error}
    finally:
        with STATE_LOCK:
            STATE["scan_running"] = False
        SCAN_LOCK.release()


def current_15m_bucket() -> str:
    now = utc_now()
    return now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0).isoformat()


def scanner_loop() -> None:
    log_event("INFO", "scanner loop started", {"poll_seconds": SETTINGS.poll_seconds})
    while True:
        try:
            bucket = current_15m_bucket()
            now = utc_now()
            if not STATE.get("paused") and now.minute % 15 <= 2 and bucket != STATE.get("last_completed_bucket"):
                result = execute_scan("scheduled")
                if result.get("ok"):
                    with STATE_LOCK:
                        STATE["last_completed_bucket"] = bucket
        except Exception as exc:
            log_event("ERROR", "scanner loop error", {"error": repr(exc)})
        time.sleep(SETTINGS.poll_seconds)


def query_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with DB_LOCK, connect_db() as conn:
        return [row_dict(row) for row in conn.execute(sql, params)]


def status_payload() -> dict[str, Any]:
    def count(sql: str) -> int:
        rows = query_rows(sql)
        return int(rows[0]["n"] if rows else 0)
    latest_scan = query_rows("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1")
    with STATE_LOCK:
        state = dict(STATE)
    return {
        "ok": True,
        "project_id": SETTINGS.project_id,
        "project_name": SETTINGS.project_name,
        "baseline": BASELINE_NAME,
        "mode": "paper_only_no_orders",
        "state": state,
        "universe_count": len(state.get("universe") or []),
        "candidates_total": count("SELECT COUNT(*) AS n FROM candidates"),
        "ready_total": count("SELECT COUNT(*) AS n FROM candidates WHERE final_status='READY'"),
        "open_trades": count("SELECT COUNT(*) AS n FROM paper_trades WHERE status='open'"),
        "closed_trades": count("SELECT COUNT(*) AS n FROM paper_trades WHERE status='closed'"),
        "history_seed_trades": count("SELECT COUNT(*) AS n FROM history_trades"),
        "kill_status": kill_status(),
        "latest_scan": latest_scan[0] if latest_scan else {},
        "time_utc": iso_now(),
    }


DASHBOARD_HTML = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMOKE Control</title><style>body{font-family:Arial,sans-serif;margin:0;background:#111827;color:#e5e7eb}header{padding:18px 24px;background:#0b1220;position:sticky;top:0}main{padding:20px;max-width:1300px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:14px}.big{font-size:28px;font-weight:700}.ok{color:#34d399}.bad{color:#f87171}.watch{color:#fbbf24}button{padding:10px 14px;border:0;border-radius:8px;margin:4px;cursor:pointer}table{width:100%;border-collapse:collapse;background:#1f2937;margin-top:12px}th,td{padding:9px;border-bottom:1px solid #374151;text-align:left;font-size:13px}pre{white-space:pre-wrap}.section{margin-top:22px;overflow:auto}</style></head><body><header><b>SMOKE CONTROL</b> — единая панель paper-наблюдения</header><main><div><button onclick="post('/api/scan')">Проверить сейчас</button><button onclick="post('/api/resume')">Запустить</button><button onclick="post('/api/pause')">Пауза</button></div><div id="cards" class="grid"></div><div class="section"><h2>Последние кандидаты</h2><table><thead><tr><th>Время</th><th>Монета</th><th>Сторона</th><th>Статус</th><th>Вход</th><th>Стоп</th><th>TP</th><th>RR</th><th>Quality</th><th>Structure</th></tr></thead><tbody id="candidates"></tbody></table></div><div class="section"><h2>Paper-сделки</h2><table><thead><tr><th>Вход</th><th>Монета</th><th>Сторона</th><th>Статус</th><th>Результат R</th><th>Причина выхода</th></tr></thead><tbody id="trades"></tbody></table></div><div class="section"><h2>События</h2><pre id="events"></pre></div><script>async function api(path,opt){let r=await fetch(path,opt);if(!r.ok)throw new Error(await r.text());return r.json()}async function post(path){await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});setTimeout(load,500)}function cls(v){return v===true||v==='ok'||v==='READY'?'ok':v==='error'||v==='BLOCKED'?'bad':'watch'}async function load(){try{let s=await api('/api/status');document.getElementById('cards').innerHTML=`<div class=card><div>Проект</div><div class=big>${s.project_name}</div></div><div class=card><div>Сканер</div><div class="big ${s.state.paused?'watch':'ok'}">${s.state.paused?'ПАУЗА':'РАБОТАЕТ'}</div></div><div class=card><div>Монет</div><div class=big>${s.universe_count}</div></div><div class=card><div>Готовых сетапов</div><div class="big ok">${s.ready_total}</div></div><div class=card><div>Открыто paper</div><div class=big>${s.open_trades}</div></div><div class=card><div>Последний скан</div><div class="${cls(s.state.last_scan_status)}">${s.state.last_scan_status}</div><small>${s.state.last_scan_finished||''}</small></div>`;let c=await api('/api/candidates?limit=50');document.getElementById('candidates').innerHTML=c.items.map(x=>`<tr><td>${x.entry_time}</td><td>${x.symbol}</td><td>${x.side}</td><td class=${cls(x.final_status)}>${x.final_status}</td><td>${x.entry_price}</td><td>${x.stop_price}</td><td>${x.target_price}</td><td>${x.target_rr}</td><td>${x.quality_decision}</td><td>${x.structure_decision}</td></tr>`).join('');let t=await api('/api/trades?limit=50');document.getElementById('trades').innerHTML=t.items.map(x=>`<tr><td>${x.entry_time}</td><td>${x.symbol}</td><td>${x.side}</td><td>${x.status}</td><td>${x.result_r}</td><td>${x.exit_reason}</td></tr>`).join('');let e=await api('/api/events?limit=20');document.getElementById('events').textContent=e.items.map(x=>`${x.event_time} [${x.level}] ${x.message}`).join('\n')}catch(e){document.getElementById('events').textContent='Ошибка: '+e}}load();setInterval(load,5000)</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SmokeControl/2.0"

    def _authorized(self) -> bool:
        if not SETTINGS.admin_password:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, password = base64.b64decode(auth[6:]).decode("utf-8").split(":", 1)
                return secrets.compare_digest(user, SETTINGS.admin_user) and secrets.compare_digest(password, SETTINGS.admin_password)
            except Exception:
                return False
        secret = self.headers.get("X-Smoke-Secret", "")
        return bool(SETTINGS.api_secret) and secrets.compare_digest(secret, SETTINGS.api_secret)

    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="SMOKE"')
        self.end_headers(); self.wfile.write(body)

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "project_id": SETTINGS.project_id, "time_utc": iso_now()}); return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"}); return
        if parsed.path == "/":
            self._send(200, DASHBOARD_HTML, "text/html; charset=utf-8"); return
        limit = min(500, max(1, int(parse_qs(parsed.query).get("limit", ["100"])[0])))
        if parsed.path == "/api/status":
            self._send(200, status_payload())
        elif parsed.path == "/api/candidates":
            self._send(200, {"items": query_rows("SELECT * FROM candidates ORDER BY entry_time DESC LIMIT ?", (limit,))})
        elif parsed.path.startswith("/api/candidates/"):
            key = parsed.path[len("/api/candidates/"):]
            rows = query_rows("SELECT * FROM candidates WHERE candidate_key=?", (key,))
            layers = query_rows("SELECT * FROM layer_results WHERE candidate_key=? ORDER BY rowid ASC", (key,))
            self._send(200 if rows else 404, {"candidate": rows[0] if rows else None, "layers": layers})
        elif parsed.path == "/api/trades":
            self._send(200, {"items": query_rows("SELECT * FROM paper_trades ORDER BY entry_time DESC LIMIT ?", (limit,))})
        elif parsed.path == "/api/events":
            self._send(200, {"items": query_rows("SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (limit,))})
        elif parsed.path == "/api/projects":
            self._send(200, {"items": [{"project_id": SETTINGS.project_id, "project_name": SETTINGS.project_name, "status_url": "/api/status"}]})
        else:
            self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"}); return
        try:
            payload = self._json()
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid_json"}); return
        if self.path == "/api/scan":
            threading.Thread(target=execute_scan, args=("manual",), daemon=True).start(); self._send(202, {"ok": True, "started": True})
        elif self.path == "/api/pause":
            with STATE_LOCK: STATE["paused"] = True
            setting_set("paused", "true"); self._send(200, {"ok": True, "paused": True})
        elif self.path == "/api/resume":
            with STATE_LOCK: STATE["paused"] = False
            setting_set("paused", "false"); self._send(200, {"ok": True, "paused": False})
        elif self.path == "/api/universe/refresh":
            self._send(200, {"ok": True, "symbols": refresh_universe()})
        elif self.path == "/api/settings":
            changed = {}
            for key, value in payload.items():
                if key == "paused": setting_set(key, value); changed[key] = value
            self._send(200, {"ok": True, "changed": changed})
        else:
            self._send(404, {"ok": False, "error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{iso_now()}] {self.client_address[0]} {fmt % args}")


def main() -> int:
    init_schema()
    paused_saved = setting_get("paused", "")
    if paused_saved:
        with STATE_LOCK: STATE["paused"] = parse_bool(paused_saved, STATE["paused"])
    refresh_universe()
    if not STATE["paused"]:
        threading.Thread(target=execute_scan, args=("startup",), daemon=True).start()
    threading.Thread(target=scanner_loop, daemon=True).start()
    server = ThreadingHTTPServer((SETTINGS.host, SETTINGS.port), Handler)
    log_event("INFO", "SMOKE control server started", {"host": SETTINGS.host, "port": SETTINGS.port, "project_id": SETTINGS.project_id})
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
