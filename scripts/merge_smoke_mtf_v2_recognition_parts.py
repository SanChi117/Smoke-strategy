#!/usr/bin/env python3
"""Merge sharded SMOKE MTF V2 no-PnL recognition exports.

Sharding changes execution only. The merger reapplies the frozen global rule:
first N observations chronologically per symbol, side and setup_state.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from strategy_lab.mtf_recognition_export_v2 import assert_no_outcome_fields

CSV_FIELDS = [
    "timestamp",
    "symbol",
    "side",
    "setup_state",
    "entry_ready",
    "scenario",
    "scenario_strength",
    "daily_state",
    "h4_state",
    "poi_timeframe",
    "poi_kind",
    "poi_source",
    "poi_strength",
    "h1_raid",
    "h1_vc",
    "vc_zone_test",
    "m5_bos",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "target_timeframe",
    "target_source",
    "planned_rr",
    "quality_score",
    "quality_state",
    "reasons",
]


def _load_parts(root: Path) -> list[dict[str, Any]]:
    files = sorted(root.rglob("recognition_candidates.json"))
    if not files:
        raise RuntimeError(f"no recognition_candidates.json parts under {root}")
    parts: list[dict[str, Any]] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"invalid part root: {path}")
        assert_no_outcome_fields(payload)
        if payload.get("mode") != "NO_PNL_NO_FUTURE_OUTCOME":
            raise RuntimeError(f"unexpected part mode: {path}")
        if not isinstance(payload.get("candidates"), list):
            raise RuntimeError(f"part candidates missing: {path}")
        parts.append(payload)
    return parts


def merge_parts(
    parts: list[dict[str, Any]],
    scan_start: str,
    scan_end: str,
    per_group: int,
    expected_parts: int | None = None,
) -> dict[str, Any]:
    if expected_parts is not None and len(parts) != expected_parts:
        raise RuntimeError(f"expected {expected_parts} parts, found {len(parts)}")

    state_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    evaluated_15m_bars = 0
    evaluated_side_snapshots = 0
    qualifying_snapshots = 0

    for part in parts:
        evaluated_15m_bars += int(part.get("evaluated_15m_bars", 0))
        evaluated_side_snapshots += int(part.get("evaluated_side_snapshots", 0))
        qualifying_snapshots += int(part.get("qualifying_snapshots", 0))
        state_counts.update({str(k): int(v) for k, v in dict(part.get("state_counts") or {}).items()})
        reason_counts.update({str(k): int(v) for k, v in dict(part.get("reason_counts") or {}).items()})
        candidates.extend(part["candidates"])

    # Every shard already kept the first N rows in each local group. Therefore
    # those rows contain every possible member of the first N global rows.
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    ordered = sorted(candidates, key=lambda row: (row["timestamp"], row["symbol"], row["side"]))
    for row in ordered:
        key = (str(row["symbol"]), str(row["side"]), str(row["setup_state"]))
        if len(groups[key]) < per_group:
            groups[key].append(row)

    selected = [row for key in sorted(groups) for row in groups[key]]
    selected.sort(key=lambda row: (row["timestamp"], row["symbol"], row["side"]))

    result = {
        "study_id": "SMOKE_MTF_V2_REAL_RECOGNITION_CANDIDATES",
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "scan_start": scan_start,
        "scan_end": scan_end,
        "evaluated_15m_bars": evaluated_15m_bars,
        "evaluated_side_snapshots": evaluated_side_snapshots,
        "qualifying_snapshots": qualifying_snapshots,
        "selected_snapshots": len(selected),
        "selection_rule": "first N chronologically per symbol, side and setup_state",
        "per_group": per_group,
        "shard_count": len(parts),
        "state_counts": dict(sorted(state_counts.items())),
        "reason_counts": dict(reason_counts.most_common(30)),
        "candidates": selected,
    }
    assert_no_outcome_fields(result)
    return result


def _write_csv(path: Path, candidates: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            poi = candidate.get("poi") or {}
            writer.writerow(
                {
                    "timestamp": candidate.get("timestamp"),
                    "symbol": candidate.get("symbol"),
                    "side": candidate.get("side"),
                    "setup_state": candidate.get("setup_state"),
                    "entry_ready": candidate.get("entry_ready"),
                    "scenario": candidate.get("scenario"),
                    "scenario_strength": candidate.get("scenario_strength"),
                    "daily_state": candidate.get("daily_state"),
                    "h4_state": candidate.get("h4_state"),
                    "poi_timeframe": poi.get("timeframe"),
                    "poi_kind": poi.get("kind"),
                    "poi_source": poi.get("source"),
                    "poi_strength": poi.get("strength"),
                    "h1_raid": candidate.get("h1_raid"),
                    "h1_vc": candidate.get("h1_vc"),
                    "vc_zone_test": candidate.get("vc_zone_test"),
                    "m5_bos": candidate.get("m5_bos"),
                    "planned_entry": candidate.get("planned_entry"),
                    "planned_stop": candidate.get("planned_stop"),
                    "planned_target": candidate.get("planned_target"),
                    "target_timeframe": candidate.get("target_timeframe"),
                    "target_source": candidate.get("target_source"),
                    "planned_rr": candidate.get("planned_rr"),
                    "quality_score": candidate.get("quality_score"),
                    "quality_state": candidate.get("quality_state"),
                    "reasons": "|".join(candidate.get("reasons") or []),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge no-PnL SMOKE MTF V2 recognition shards")
    parser.add_argument("--parts-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--scan-start", required=True)
    parser.add_argument("--scan-end", required=True)
    parser.add_argument("--per-group", type=int, default=4)
    parser.add_argument("--expected-parts", type=int)
    args = parser.parse_args()

    parts = _load_parts(Path(args.parts_root))
    result = merge_parts(
        parts,
        args.scan_start,
        args.scan_end,
        max(1, args.per_group),
        args.expected_parts,
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "recognition_candidates.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {key: value for key, value in result.items() if key != "candidates"}
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(out / "recognition_candidates.csv", result["candidates"])
    print(
        f"Merged {len(parts)} shards: {result['selected_snapshots']} selected from "
        f"{result['qualifying_snapshots']} qualifying snapshots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
