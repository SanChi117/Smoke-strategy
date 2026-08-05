#!/usr/bin/env python3
"""Causal scheduled-event risk layer for SMOKE MTF V2.

The module deliberately separates scheduled event risk from directional trading
logic. High-impact events can block new entries; medium-impact events can reduce
risk. Historical research must consume a frozen point-in-time snapshot rather
than a modern reconstructed calendar.

API keys are read by callers and must never be committed. Research only: this
module does not place paper or live orders.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def utc_naive(value: datetime | str) -> datetime:
    """Return a timezone-naive UTC datetime for deterministic comparisons."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@dataclass(frozen=True)
class ScheduledEvent:
    event_id: str
    title: str
    start: datetime
    end: datetime
    importance: int
    scope: str
    provider: str
    symbols: tuple[str, ...] = ()
    estimated: bool = False
    known_at: datetime | None = None
    category: str = ""
    source_url: str = ""
    raw_importance: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", utc_naive(self.start))
        object.__setattr__(self, "end", utc_naive(self.end))
        if self.end < self.start:
            object.__setattr__(self, "end", self.start)
        if self.known_at is not None:
            object.__setattr__(self, "known_at", utc_naive(self.known_at))
        object.__setattr__(self, "importance", max(1, min(3, int(self.importance))))
        object.__setattr__(
            self,
            "symbols",
            tuple(sorted({str(symbol).upper().replace("USDT", "") for symbol in self.symbols if symbol})),
        )


@dataclass(frozen=True)
class EventRiskPolicy:
    macro_high_before_minutes: int = 60
    macro_high_after_minutes: int = 45
    macro_medium_before_minutes: int = 30
    macro_medium_after_minutes: int = 20
    macro_medium_risk_multiplier: float = 0.50
    crypto_high_before_minutes: int = 120
    crypto_high_after_minutes: int = 120
    crypto_medium_before_minutes: int = 60
    crypto_medium_after_minutes: int = 60
    crypto_medium_risk_multiplier: float = 0.65
    estimated_event_risk_multiplier: float = 0.75


@dataclass(frozen=True)
class EventRiskDecision:
    timestamp: datetime
    symbol: str
    block_new_entry: bool
    risk_multiplier: float
    active_event_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def _symbol_base(symbol: str) -> str:
    text = str(symbol).upper().replace("/", "").replace("_", "")
    for suffix in ("USDT", "USDC", "BUSD", "USD"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _event_matches(event: ScheduledEvent, symbol: str) -> bool:
    if event.scope in {"global", "macro"}:
        return True
    if event.scope != "crypto":
        return False
    if not event.symbols:
        return True
    return _symbol_base(symbol) in set(event.symbols)


def _window(event: ScheduledEvent, policy: EventRiskPolicy) -> tuple[datetime, datetime, float, bool]:
    if event.scope in {"global", "macro"}:
        if event.importance >= 3:
            before = policy.macro_high_before_minutes
            after = policy.macro_high_after_minutes
            multiplier = 0.0
            hard = True
        else:
            before = policy.macro_medium_before_minutes
            after = policy.macro_medium_after_minutes
            multiplier = policy.macro_medium_risk_multiplier
            hard = False
    else:
        if event.importance >= 3:
            before = policy.crypto_high_before_minutes
            after = policy.crypto_high_after_minutes
            multiplier = 0.0
            hard = True
        else:
            before = policy.crypto_medium_before_minutes
            after = policy.crypto_medium_after_minutes
            multiplier = policy.crypto_medium_risk_multiplier
            hard = False

    # An estimated date is a deadline/window rather than a precise event time.
    # It must never generate a false minute-level hard blackout.
    if event.estimated:
        hard = False
        multiplier = min(multiplier if multiplier > 0 else 1.0, policy.estimated_event_risk_multiplier)
        before = max(before, 24 * 60)
        after = max(after, 24 * 60)
    return (
        event.start - timedelta(minutes=before),
        event.end + timedelta(minutes=after),
        multiplier,
        hard,
    )


def evaluate_event_risk(
    timestamp: datetime,
    symbol: str,
    events: Iterable[ScheduledEvent],
    policy: EventRiskPolicy | None = None,
) -> EventRiskDecision:
    """Evaluate only events that were already known at ``timestamp``."""
    at = utc_naive(timestamp)
    cfg = policy or EventRiskPolicy()
    risk_multiplier = 1.0
    block = False
    ids: list[str] = []
    reasons: list[str] = []

    for event in sorted(events, key=lambda item: (item.start, item.event_id)):
        if event.known_at is not None and event.known_at > at:
            continue
        if not _event_matches(event, symbol):
            continue
        left, right, multiplier, hard = _window(event, cfg)
        if not (left <= at <= right):
            continue
        ids.append(event.event_id)
        kind = "estimated" if event.estimated else "scheduled"
        reasons.append(
            f"{event.provider}:{event.scope}:{event.importance}:{kind}:{event.title}"
        )
        if hard:
            block = True
            risk_multiplier = 0.0
        elif not block:
            risk_multiplier = min(risk_multiplier, max(0.0, multiplier))

    return EventRiskDecision(
        timestamp=at,
        symbol=str(symbol).upper(),
        block_new_entry=block,
        risk_multiplier=round(risk_multiplier, 6),
        active_event_ids=tuple(ids),
        reasons=tuple(reasons),
    )


def _json_request(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> object:
    request = Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed HTTPS provider URLs
        return json.loads(response.read().decode("utf-8"))


class TradingEconomicsCalendarClient:
    """Normalize Trading Economics economic calendar records."""

    base_url = "https://api.tradingeconomics.com"

    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("Trading Economics API key is required")
        self.api_key = api_key
        self.timeout = timeout

    def fetch(
        self,
        start: datetime,
        end: datetime,
        countries: tuple[str, ...] = ("united states",),
        importance_min: int = 2,
        acquired_at: datetime | None = None,
    ) -> list[ScheduledEvent]:
        country_path = quote(",".join(countries), safe=",")
        start_text = utc_naive(start).date().isoformat()
        end_text = utc_naive(end).date().isoformat()
        query = urlencode({"c": self.api_key, "importance": importance_min, "f": "json"})
        url = f"{self.base_url}/calendar/country/{country_path}/{start_text}/{end_text}?{query}"
        payload = _json_request(url, timeout=self.timeout)
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected Trading Economics calendar response")
        known = utc_naive(acquired_at or datetime.now(timezone.utc))
        output: list[ScheduledEvent] = []
        for row in payload:
            if not isinstance(row, dict) or not row.get("Date"):
                continue
            event_time = utc_naive(str(row["Date"]))
            estimated = str(row.get("DateSpan", "0")) != "0"
            output.append(
                ScheduledEvent(
                    event_id=f"te:{row.get('CalendarId', '')}",
                    title=str(row.get("Event") or row.get("Category") or "Economic event"),
                    start=event_time,
                    end=event_time,
                    importance=int(row.get("Importance") or 1),
                    scope="macro",
                    provider="trading_economics",
                    estimated=estimated,
                    known_at=known,
                    category=str(row.get("Category") or ""),
                    source_url=str(row.get("SourceURL") or ""),
                    raw_importance=str(row.get("Importance") or ""),
                )
            )
        return output


class CoinMarketCalClient:
    """Normalize CoinMarketCal v2 crypto events with cursor pagination."""

    base_url = "https://api.coinmarketcal.com/v2/events"

    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("CoinMarketCal API key is required")
        self.api_key = api_key
        self.timeout = timeout

    @staticmethod
    def _importance(value: object) -> int:
        if isinstance(value, (int, float)):
            return 3 if float(value) >= 7.5 else 2 if float(value) >= 5.0 else 1
        text = str(value or "").strip().lower()
        if text in {"critical", "high"}:
            return 3
        if text in {"mid", "medium"}:
            return 2
        return 1

    def fetch(
        self,
        start: datetime,
        end: datetime,
        coin_slugs: tuple[str, ...] = (),
        impact_min: float | None = 5.0,
        acquired_at: datetime | None = None,
    ) -> list[ScheduledEvent]:
        cursor: str | None = None
        output: list[ScheduledEvent] = []
        known = utc_naive(acquired_at or datetime.now(timezone.utc))
        while True:
            params: dict[str, object] = {
                "from": utc_naive(start).isoformat() + "Z",
                "to": utc_naive(end).isoformat() + "Z",
                "limit": 100,
                "sortBy": "date_asc",
            }
            if coin_slugs:
                params["coins"] = ",".join(coin_slugs)
            if impact_min is not None:
                params["impactMin"] = impact_min
            if cursor:
                params["cursor"] = cursor
            payload = _json_request(
                f"{self.base_url}?{urlencode(params)}",
                headers={"x-api-key": self.api_key},
                timeout=self.timeout,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise RuntimeError("Unexpected CoinMarketCal events response")
            for row in payload["data"]:
                if not isinstance(row, dict) or not row.get("date"):
                    continue
                start_at = utc_naive(str(row["date"]))
                end_at = utc_naive(str(row.get("dateEnd") or row["date"]))
                symbols = tuple(
                    str(coin.get("symbol") or "")
                    for coin in (row.get("coins") or [])
                    if isinstance(coin, dict)
                )
                impact = row.get("impact")
                output.append(
                    ScheduledEvent(
                        event_id=f"cmc:{row.get('id', '')}",
                        title=str(row.get("title") or "Crypto event"),
                        start=start_at,
                        end=end_at,
                        importance=self._importance(impact),
                        scope="crypto",
                        provider="coinmarketcal",
                        symbols=symbols,
                        estimated=bool(row.get("isEstimated")),
                        known_at=known,
                        category=",".join(str(item) for item in (row.get("categories") or [])),
                        source_url=str(row.get("sourceUrl") or ""),
                        raw_importance=str(impact or ""),
                    )
                )
            meta = payload.get("meta") or {}
            cursor = str(meta.get("cursor")) if meta.get("cursor") else None
            if not cursor:
                break
        return output


def write_frozen_events(path: str | Path, events: Iterable[ScheduledEvent], acquired_at: datetime) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for event in sorted(events, key=lambda item: (item.start, item.event_id)):
        row = asdict(event)
        row["start"] = event.start.isoformat(timespec="seconds")
        row["end"] = event.end.isoformat(timespec="seconds")
        row["known_at"] = event.known_at.isoformat(timespec="seconds") if event.known_at else None
        row["symbols"] = list(event.symbols)
        rows.append(row)
    payload = {
        "schema": "smoke_scheduled_events_v1",
        "acquired_at_utc": utc_naive(acquired_at).isoformat(timespec="seconds"),
        "events": rows,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_frozen_events(path: str | Path) -> list[ScheduledEvent]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "smoke_scheduled_events_v1":
        raise ValueError("Unsupported scheduled event snapshot schema")
    output: list[ScheduledEvent] = []
    for row in payload.get("events") or []:
        output.append(
            ScheduledEvent(
                event_id=str(row["event_id"]),
                title=str(row["title"]),
                start=utc_naive(row["start"]),
                end=utc_naive(row["end"]),
                importance=int(row["importance"]),
                scope=str(row["scope"]),
                provider=str(row["provider"]),
                symbols=tuple(row.get("symbols") or ()),
                estimated=bool(row.get("estimated")),
                known_at=utc_naive(row["known_at"]) if row.get("known_at") else None,
                category=str(row.get("category") or ""),
                source_url=str(row.get("source_url") or ""),
                raw_importance=str(row.get("raw_importance") or ""),
            )
        )
    return output
