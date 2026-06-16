#!/usr/bin/env python3
"""Smoke paper-review server.

Runs the final tagged MTF HYBRID v2 baseline in paper-only mode.
No exchange API keys. No private endpoints. No real orders.

Modes:
- HTTP paper server for webhooks and status/export endpoints;
- optional public-data scanner that opens virtual paper trades only.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy_lab.binance_market_data import load_binance_futures_candles  # noqa: E402
from strategy_lab.market_data import Candle, group_candles_by_symbol, read_candles_csv  # noqa: E402
from strategy_lab.mtf_feature_builder import build_features  # noqa: E402
from strategy_lab.risk_model import RiskPlan, build_risk_plans  # noqa: E402
from strategy_lab.setup_generator import generate_candidate_setups  # noqa: E402


FINAL_BASELINE = "TAGGED_MTF_NO_DIRECTION_BLOCK_V1"
ALLOWED_SETUP_TYPES = {"pullback", "ignition"}
ALLOWED_DIRECTION_CONTEXTS = {"down"}
BLOCKED_SETUP_TYPES = {"breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"}
BLOCKED_VOLATILITY_REGIMES = {"high"}
BLOCKED_LIQUIDITY_STATES = {"high_sweep_reject"}
BLOCKED_CANDLE_TYPES = {"bear_rejection"}
MIN_CONFIDENCE = 43.0
MIN_VOLUME_RATIO = 0.70


DEFAULT_SYMBOLS = "INJUSDT,TONUSDT,DOGEUSDT,ARBUSDT,NEARUSDT,OPUSDT"


def now_utc() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_dt(value: str | datetime) -> datetime:
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
        env_file = Path(os.environ.get("SMOKE_ENV_FILE", ROOT / ".env.paper"))
        read_env_file(env_file)
        self.host = os.environ.get("SMOKE_HOST", "0.0.0.0")
        self.port = int(os.environ.get("SMOKE_PORT", "8095"))
        self.secret = os.environ.get("SMOKE_PAPER_SECRET", "")
        self.runtime_dir = Path(os.environ.get("SMOKE_RUNTIME_DIR", ROOT / "runtime" / "paper_review"))
        self.db_path = Path(os.environ.get("SMOKE_DB_PATH", self.runtime_dir / "paper_review.sqlite3"))
        self.auto_scan = parse_bool(os.environ.get("SMOKE_AUTO_SCAN"), True)
        self.scan_interval_sec = int(os.environ.get("SMOKE_SCAN_INTERVAL_SEC", "900"))
        self.candle_limit = int(os.environ.get("SMOKE_CANDLE_LIMIT", "1200"))
        self.sleep_sec = float(os.environ.get("SMOKE_BINANCE_SLEEP_SEC", "0.03"))
        self.symbols_file = os.environ.get("SMOKE_SYMBOLS_FILE", "")
        self.symbols = os.environ.get("SMOKE_SYMBOLS", DEFAULT_SYMBOLS)
        self.daily_dd_stop_pct = float(os.environ.get("SMOKE_DAILY_DD_STOP_PCT", "2.0"))
        self.weekly_dd_stop_pct = float(os.environ.get("SMOKE_WEEKLY_DD_STOP_PCT", "5.0"))
        self.max_stop_streak = int(os.environ.get("SMOKE_MAX_STOP_STREAK", "3"))
        self.max_open_per_symbol = int(os.environ.get("SMOKE_MAX_OPEN_PER_SYMBOL", "1"))
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def symbols_list(self) -> list[str]:
        if self.symbols_file:
            p = Path(self.symbols_file)
            if p.exists():
                text = p.read_text(encoding="utf-8")
                return [x.strip().upper() for x in text.replace("\n", ",").split(",") if x.strip()]
        return [x.strip().upper() for x in self.symbols.replace("\n", ",").split(",") if x.strip()]


SETTINGS = Settings()
DB_LOCK = threading.Lock()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(SETTINGS.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with DB_LOCK, connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                target_rr REAL DEFAULT 0,
                setup_type TEXT DEFAULT '',
                trend_context TEXT DEFAULT '',
                direction_context TEXT DEFAULT '',
                volatility_regime TEXT DEFAULT '',
                structure_type TEXT DEFAULT '',
                confidence_hint REAL DEFAULT 0,
                risk_grade TEXT DEFAULT '',
                target_policy TEXT DEFAULT '',
                micro_confirm_state TEXT DEFAULT 'not_used',
                source TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                exit_time TEXT DEFAULT '',
                exit_price REAL DEFAULT 0,
                exit_reason TEXT DEFAULT '',
                result_r REAL DEFAULT 0,
                result_pct REAL DEFAULT 0,
                raw_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT DEFAULT ''
            )
            """
        )
        conn.commit()


def log_event(level: str, message: str, payload: Any | None = None) -> None:
    text = "" if payload is None else json.dumps(payload, ensure_ascii=False, default=str)
    with DB_LOCK, connect_db() as conn:
        conn.execute(
            "INSERT INTO paper_events(event_time, level, message, payload) VALUES (?, ?, ?, ?)",
            (now_utc(), level, message, text),
        )
        conn.commit()
    print(f"[{level}] {message}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def extract_reason_value(reason: str, key: str) -> str:
    prefix = f"{key}="
    for part in str(reason).split("|"):
        if part.startswith(prefix):
            return part[len(prefix):].strip().lower()
    return ""


def extract_reason_float(reason: str, key: str, default: float = 0.0) -> float:
    try:
        return float(extract_reason_value(reason, key) or default)
    except ValueError:
        return default


def plan_passes_final_filter(plan: RiskPlan) -> tuple[bool, str]:
    reason = str(plan.reason)
    setup = plan.setup_type.lower()
    direction = extract_reason_value(reason, "dir")
    liq = extract_reason_value(reason, "liq")
    candle = extract_reason_value(reason, "candle")
    vol_ratio = extract_reason_float(reason, "vr", 0.0)

    if setup not in ALLOWED_SETUP_TYPES:
        return False, "setup_not_allowed"
    if setup in BLOCKED_SETUP_TYPES:
        return False, "setup_blocked"
    if direction not in ALLOWED_DIRECTION_CONTEXTS:
        return False, "direction_not_allowed"
    if plan.volatility_regime.lower() in BLOCKED_VOLATILITY_REGIMES:
        return False, "volatility_blocked"
    if liq in BLOCKED_LIQUIDITY_STATES:
        return False, "liquidity_blocked"
    if candle in BLOCKED_CANDLE_TYPES:
        return False, "candle_blocked"
    if vol_ratio < MIN_VOLUME_RATIO:
        return False, "volume_ratio_too_low"
    return True, "allowed_final_hybrid_v2"


def trade_id(symbol: str, side: str, entry_time: str) -> str:
    clean_time = entry_time.replace(":", "").replace("-", "").replace("T", "_").replace(" ", "_")
    return f"{FINAL_BASELINE}_{symbol.upper()}_{side.lower()}_{clean_time}"


def kill_status() -> dict[str, Any]:
    today = datetime.utcnow().date().isoformat()
    week_start = (datetime.utcnow().date() - timedelta(days=datetime.utcnow().weekday())).isoformat()
    with DB_LOCK, connect_db() as conn:
        rows = [row_to_dict(r) for r in conn.execute("SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_time ASC")]
    daily = sum(float(r["result_pct"] or 0) for r in rows if str(r.get("exit_time", ""))[:10] == today)
    weekly = sum(float(r["result_pct"] or 0) for r in rows if str(r.get("exit_time", ""))[:10] >= week_start)
    streak = 0
    for r in reversed(rows):
        if str(r.get("exit_reason", "")).lower() == "stop_loss":
            streak += 1
        else:
            break
    reasons = []
    if daily <= -abs(SETTINGS.daily_dd_stop_pct):
        reasons.append("daily_drawdown_stop")
    if weekly <= -abs(SETTINGS.weekly_dd_stop_pct):
        reasons.append("weekly_drawdown_stop")
    if streak >= SETTINGS.max_stop_streak:
        reasons.append("stop_loss_streak")
    return {
        "blocked": bool(reasons),
        "reasons": reasons,
        "daily_result_pct": round(daily, 4),
        "weekly_result_pct": round(weekly, 4),
        "consecutive_stop_losses": streak,
    }


def open_symbol_count(symbol: str) -> int:
    with DB_LOCK, connect_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM paper_trades WHERE status='open' AND symbol=?", (symbol.upper(),)).fetchone()
    return int(row["n"] if row else 0)


def save_open_trade(data: dict[str, Any]) -> dict[str, Any]:
    symbol = str(data["symbol"]).upper()
    side = str(data["side"]).lower()
    entry_time = str(data["entry_time"])
    paper_id = str(data.get("paper_trade_id") or trade_id(symbol, side, entry_time))
    ks = kill_status()
    if ks["blocked"]:
        return {"opened": False, "reason": "kill_switch_blocked", "kill_status": ks}
    if open_symbol_count(symbol) >= SETTINGS.max_open_per_symbol:
        return {"opened": False, "reason": "max_open_per_symbol", "symbol": symbol}

    now = now_utc()
    with DB_LOCK, connect_db() as conn:
        exists = conn.execute("SELECT paper_trade_id FROM paper_trades WHERE paper_trade_id=?", (paper_id,)).fetchone()
        if exists:
            return {"opened": False, "reason": "duplicate", "paper_trade_id": paper_id}
        conn.execute(
            """
            INSERT INTO paper_trades(
                paper_trade_id, symbol, side, entry_time, entry_price, stop_price, target_price,
                target_rr, setup_type, trend_context, direction_context, volatility_regime, structure_type,
                confidence_hint, risk_grade, target_policy, micro_confirm_state, source, raw_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id, symbol, side, entry_time, float(data["entry_price"]), float(data["stop_price"]),
                float(data["target_price"]), float(data.get("target_rr", 0) or 0), str(data.get("setup_type", "")),
                str(data.get("trend_context", "")), str(data.get("direction_context", "")),
                str(data.get("volatility_regime", "")), str(data.get("structure_type", "")),
                float(data.get("confidence_hint", 0) or 0), str(data.get("risk_grade", "")),
                str(data.get("target_policy", "")), str(data.get("micro_confirm_state", "not_used")),
                str(data.get("source", "")), str(data.get("raw_reason", "")), now, now,
            ),
        )
        conn.commit()
    log_event("INFO", "paper trade opened", {"paper_trade_id": paper_id, "symbol": symbol, "side": side})
    return {"opened": True, "paper_trade_id": paper_id}


def close_trade(row: dict[str, Any], exit_time: str, exit_price: float, exit_reason: str) -> None:
    entry = float(row["entry_price"])
    stop = float(row["stop_price"])
    side = str(row["side"]).lower()
    risk = abs(entry - stop) or 1e-12
    if side == "short":
        result_r = (entry - exit_price) / risk
        result_pct = (entry - exit_price) / entry * 100.0
    else:
        result_r = (exit_price - entry) / risk
        result_pct = (exit_price - entry) / entry * 100.0
    with DB_LOCK, connect_db() as conn:
        conn.execute(
            """
            UPDATE paper_trades
            SET status='closed', exit_time=?, exit_price=?, exit_reason=?, result_r=?, result_pct=?, updated_at=?
            WHERE paper_trade_id=? AND status='open'
            """,
            (exit_time, round(exit_price, 8), exit_reason, round(result_r, 6), round(result_pct, 6), now_utc(), row["paper_trade_id"]),
        )
        conn.commit()
    log_event("INFO", "paper trade closed", {"paper_trade_id": row["paper_trade_id"], "reason": exit_reason, "result_r": round(result_r, 4)})


def monitor_open_trades(candles: list[Candle]) -> int:
    by_symbol = group_candles_by_symbol(candles)
    with DB_LOCK, connect_db() as conn:
        open_rows = [row_to_dict(r) for r in conn.execute("SELECT * FROM paper_trades WHERE status='open' ORDER BY entry_time ASC")]
    closed = 0
    for row in open_rows:
        symbol = str(row["symbol"]).upper()
        entry_time = parse_dt(row["entry_time"])
        side = str(row["side"]).lower()
        stop = float(row["stop_price"])
        target = float(row["target_price"])
        for candle in by_symbol.get(symbol, []):
            if candle.time <= entry_time:
                continue
            if side == "short":
                if candle.high >= stop:
                    close_trade(row, candle.time.isoformat(timespec="seconds"), stop, "stop_loss")
                    closed += 1
                    break
                if candle.low <= target:
                    close_trade(row, candle.time.isoformat(timespec="seconds"), target, "take_profit")
                    closed += 1
                    break
            else:
                if candle.low <= stop:
                    close_trade(row, candle.time.isoformat(timespec="seconds"), stop, "stop_loss")
                    closed += 1
                    break
                if candle.high >= target:
                    close_trade(row, candle.time.isoformat(timespec="seconds"), target, "take_profit")
                    closed += 1
                    break
    return closed


def scan_once() -> dict[str, Any]:
    symbols = SETTINGS.symbols_list()
    candles_csv = SETTINGS.runtime_dir / "scan_15m_candles.csv"
    market = load_binance_futures_candles(symbols=symbols, out_csv=candles_csv, interval="15m", limit=SETTINGS.candle_limit, sleep_sec=SETTINGS.sleep_sec)
    if market.status == "EMPTY":
        return {"ok": False, "reason": "empty_market_data"}
    candles = read_candles_csv(candles_csv)
    closed = monitor_open_trades(candles)
    features = build_features(candles)
    candidates = generate_candidate_setups(features, min_confidence=MIN_CONFIDENCE)
    plans = build_risk_plans(candidates)
    latest_by_symbol = {symbol: max(c.time for c in rows) for symbol, rows in group_candles_by_symbol(candles).items()}

    opened = 0
    skipped = 0
    for plan in plans:
        latest = latest_by_symbol.get(plan.symbol)
        if latest is None or parse_dt(plan.entry_time) < latest - timedelta(minutes=20):
            continue
        ok, reason = plan_passes_final_filter(plan)
        if not ok:
            skipped += 1
            continue
        direction = extract_reason_value(plan.reason, "dir")
        payload = {
            "symbol": plan.symbol,
            "side": plan.side,
            "entry_time": parse_dt(plan.entry_time).isoformat(timespec="seconds"),
            "entry_price": plan.entry,
            "stop_price": plan.stop,
            "target_price": plan.target,
            "target_rr": plan.target_rr,
            "setup_type": plan.setup_type,
            "trend_context": plan.trend_context,
            "direction_context": direction,
            "volatility_regime": plan.volatility_regime,
            "structure_type": plan.structure_type,
            "confidence_hint": plan.confidence_hint,
            "risk_grade": plan.risk_grade,
            "target_policy": plan.target_policy,
            "micro_confirm_state": "not_used",
            "source": "auto_15m_hybrid_v2_scanner",
            "raw_reason": plan.reason,
        }
        result = save_open_trade(payload)
        if result.get("opened"):
            opened += 1
    return {"ok": True, "symbols": len(symbols), "candles": len(candles), "opened": opened, "closed": closed, "skipped": skipped}


def scanner_loop() -> None:
    log_event("INFO", "scanner loop started", {"auto_scan": SETTINGS.auto_scan, "interval_sec": SETTINGS.scan_interval_sec})
    while True:
        try:
            if SETTINGS.auto_scan:
                result = scan_once()
                log_event("INFO", "scan complete", result)
        except Exception as exc:
            log_event("ERROR", "scan failed", {"error": repr(exc)})
        time.sleep(max(30, SETTINGS.scan_interval_sec))


def recent_trades(limit: int = 200) -> list[dict[str, Any]]:
    with DB_LOCK, connect_db() as conn:
        rows = [row_to_dict(r) for r in conn.execute("SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?", (limit,))]
    return rows


def status_payload() -> dict[str, Any]:
    with DB_LOCK, connect_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM paper_trades").fetchone()["n"]
        open_n = conn.execute("SELECT COUNT(*) AS n FROM paper_trades WHERE status='open'").fetchone()["n"]
        closed_n = conn.execute("SELECT COUNT(*) AS n FROM paper_trades WHERE status='closed'").fetchone()["n"]
    return {
        "ok": True,
        "baseline": FINAL_BASELINE,
        "mode": "paper_only_no_orders",
        "auto_scan": SETTINGS.auto_scan,
        "symbols": len(SETTINGS.symbols_list()),
        "total_trades": int(total),
        "open_trades": int(open_n),
        "closed_trades": int(closed_n),
        "kill_status": kill_status(),
        "db_path": str(SETTINGS.db_path),
        "time_utc": now_utc(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SmokePaperServer/1.0"

    def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        return json.loads(raw or "{}")

    def _authorized(self, payload: dict[str, Any]) -> bool:
        if not SETTINGS.secret:
            return True
        header_secret = self.headers.get("X-Smoke-Secret", "")
        body_secret = str(payload.get("secret", ""))
        return SETTINGS.secret in {header_secret, body_secret}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/health"}:
            self._send(200, {"ok": True, "mode": "paper_only_no_orders", "time_utc": now_utc()})
            return
        if parsed.path in {"/status", "/diag"}:
            self._send(200, status_payload())
            return
        if parsed.path == "/trades":
            limit = int(parse_qs(parsed.query).get("limit", ["200"])[0])
            self._send(200, {"trades": recent_trades(limit)})
            return
        if parsed.path == "/export/trades.csv":
            rows = recent_trades(100000)
            fields = list(rows[0].keys()) if rows else ["paper_trade_id", "symbol", "side", "status"]
            from io import StringIO
            buf = StringIO()
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            self._send(200, buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8")
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        try:
            payload = self._json_body()
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid_json"})
            return
        if not self._authorized(payload):
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        if self.path == "/paper-webhook":
            action = str(payload.get("action", "entry")).lower()
            if action in {"entry", "signal"}:
                try:
                    data = {
                        "symbol": payload["symbol"],
                        "side": payload.get("side", "short"),
                        "entry_time": payload.get("entry_time") or now_utc(),
                        "entry_price": float(payload["entry_price"]),
                        "stop_price": float(payload["stop_price"]),
                        "target_price": float(payload["target_price"]),
                        "target_rr": float(payload.get("target_rr", 0) or 0),
                        "setup_type": payload.get("setup_type", "external"),
                        "trend_context": payload.get("trend_context", ""),
                        "direction_context": payload.get("direction_context", ""),
                        "volatility_regime": payload.get("volatility_regime", ""),
                        "structure_type": payload.get("structure_type", ""),
                        "confidence_hint": float(payload.get("confidence_hint", 0) or 0),
                        "risk_grade": payload.get("risk_grade", ""),
                        "target_policy": payload.get("target_policy", ""),
                        "micro_confirm_state": payload.get("micro_confirm_state", "not_used"),
                        "source": payload.get("source", "external_webhook"),
                        "raw_reason": payload.get("raw_reason", json.dumps(payload, ensure_ascii=False)),
                    }
                except (KeyError, TypeError, ValueError) as exc:
                    self._send(400, {"ok": False, "error": "bad_entry_payload", "details": repr(exc)})
                    return
                self._send(200, save_open_trade(data))
                return
            if action in {"tp", "sl", "close", "exit"}:
                symbol = str(payload.get("symbol", "")).upper()
                side = str(payload.get("side", "short")).lower()
                with DB_LOCK, connect_db() as conn:
                    row = conn.execute("SELECT * FROM paper_trades WHERE status='open' AND symbol=? AND side=? ORDER BY id DESC LIMIT 1", (symbol, side)).fetchone()
                if not row:
                    self._send(404, {"ok": False, "error": "open_trade_not_found"})
                    return
                trade = row_to_dict(row)
                exit_price = float(payload.get("exit_price") or (trade["target_price"] if action == "tp" else trade["stop_price"]))
                close_trade(trade, payload.get("exit_time") or now_utc(), exit_price, "take_profit" if action == "tp" else "stop_loss" if action == "sl" else "manual_close")
                self._send(200, {"ok": True, "closed": True, "paper_trade_id": trade["paper_trade_id"]})
                return
            self._send(400, {"ok": False, "error": "unknown_action"})
            return
        if self.path == "/scan-once":
            result = scan_once()
            self._send(200, result)
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{now_utc()}] {self.client_address[0]} {fmt % args}")


def main() -> int:
    init_db()
    if SETTINGS.auto_scan:
        threading.Thread(target=scanner_loop, daemon=True).start()
    server = ThreadingHTTPServer((SETTINGS.host, SETTINGS.port), Handler)
    log_event("INFO", "paper server started", {"host": SETTINGS.host, "port": SETTINGS.port, "db": str(SETTINGS.db_path)})
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
