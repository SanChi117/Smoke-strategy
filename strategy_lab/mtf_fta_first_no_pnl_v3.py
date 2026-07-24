#!/usr/bin/env python3
"""JSON-safe outcome-blind export helpers for SMOKE MTF FTA-first V3."""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Mapping

from strategy_lab.mtf_fta_first_entry_v3 import FtaFirstPlan, plan_to_no_pnl_dict


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl",
    "future_return",
    "trade_outcome",
    "tp_result",
    "sl_result",
    "mfe",
    "mae",
    "win_rate",
    "profit_factor",
    "net_return",
    "drawdown",
    "exit_time",
    "exit_price",
    "exit_reason",
    "gross_return",
    "funding_return",
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def json_safe(value: Any) -> Any:
    """Round-trip arbitrary recognition data into deterministic JSON types."""
    return json.loads(json.dumps(value, default=_json_default, sort_keys=True))


def assert_outcome_blind(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(raw_key).lower()).strip("_")
            for fragment in FORBIDDEN_KEY_FRAGMENTS:
                if fragment in key:
                    raise AssertionError(f"forbidden outcome field at {path}.{raw_key}: {fragment}")
            assert_outcome_blind(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_outcome_blind(child, f"{path}[{index}]")


def export_plan(plan: FtaFirstPlan) -> dict[str, Any]:
    payload = json_safe(plan_to_no_pnl_dict(plan))
    assert_outcome_blind(payload)
    return payload
