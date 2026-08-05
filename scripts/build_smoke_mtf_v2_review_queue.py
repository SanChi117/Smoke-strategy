#!/usr/bin/env python3
"""Build a balanced, outcome-blind review queue from frozen recognition candidates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from strategy_lab.mtf_recognition_export_v2 import assert_no_outcome_fields

QUEUE_FIELDS = [
    "review_index",
    "timestamp",
    "symbol",
    "side",
    "setup_state",
    "stage_rank",
    "case_fingerprint",
    "cluster_size",
    "cluster_occurrence",
    "scenario",
    "daily_state",
    "h4_state",
    "poi_timeframe",
    "poi_kind",
    "poi_source",
    "h1_raid",
    "h1_vc",
    "vc_zone_test",
    "m5_bos",
    "entry_ready",
    "target_timeframe",
    "quality_state",
    "reasons",
    "packet_file",
]


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("setup_state", "")), str(row.get("side", "")), str(row.get("symbol", ""))


def case_fingerprint(row: dict[str, Any]) -> str:
    """Identify repeated structural snapshots without using timestamp or outcomes."""
    poi = row.get("poi") or {}
    identity = {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "setup_state": row.get("setup_state"),
        "scenario": row.get("scenario"),
        "monthly_state": row.get("monthly_state"),
        "weekly_state": row.get("weekly_state"),
        "daily_state": row.get("daily_state"),
        "h4_state": row.get("h4_state"),
        "h1_state": row.get("h1_state"),
        "poi": {
            "timeframe": poi.get("timeframe"),
            "kind": poi.get("kind"),
            "side": poi.get("side"),
            "low": poi.get("low"),
            "high": poi.get("high"),
            "confirmed_at": poi.get("confirmed_at"),
            "source": poi.get("source"),
        },
        "h1_raid": row.get("h1_raid"),
        "h1_vc": row.get("h1_vc"),
        "vc_zone_test": row.get("vc_zone_test"),
        "m5_bos": row.get("m5_bos"),
        "entry_ready": row.get("entry_ready"),
        "target_timeframe": row.get("target_timeframe"),
        "target_source": row.get("target_source"),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def balanced_review_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin frozen rows across state, side and symbol without dropping any."""
    groups: dict[tuple[str, str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: (item.get("timestamp", ""), item.get("symbol", ""), item.get("side", ""))):
        groups[_key(row)].append(row)
    keys = sorted(
        groups,
        key=lambda key: (
            -max(int(item.get("stage_rank", -1)) for item in groups[key]),
            key[0],
            key[1],
            key[2],
        ),
    )
    ordered: list[dict[str, Any]] = []
    while keys:
        next_keys: list[tuple[str, str, str]] = []
        for key in keys:
            if groups[key]:
                ordered.append(groups[key].popleft())
            if groups[key]:
                next_keys.append(key)
        keys = next_keys
    assert len(ordered) == len(rows)
    assert {id(row) for row in ordered} == {id(row) for row in rows}
    return ordered


def packet_payload(
    row: dict[str, Any],
    review_index: int,
    fingerprint: str,
    cluster_size: int,
    cluster_occurrence: int,
) -> dict[str, Any]:
    packet = {
        "study_id": "SMOKE_MTF_V2_RECOGNITION_REVIEW_PACKET",
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "review_index": review_index,
        "case_fingerprint": fingerprint,
        "cluster_size": cluster_size,
        "cluster_occurrence": cluster_occurrence,
        "timestamp": row.get("timestamp"),
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "setup_state": row.get("setup_state"),
        "stage_rank": row.get("stage_rank"),
        "entry_ready": row.get("entry_ready"),
        "context": {
            "scenario": row.get("scenario"),
            "scenario_strength": row.get("scenario_strength"),
            "monthly_state": row.get("monthly_state"),
            "weekly_state": row.get("weekly_state"),
            "daily_state": row.get("daily_state"),
            "h4_state": row.get("h4_state"),
            "h1_state": row.get("h1_state"),
            "long_allowed": row.get("long_allowed"),
            "short_allowed": row.get("short_allowed"),
        },
        "poi": row.get("poi"),
        "confirmation": {
            "h1_raid": row.get("h1_raid"),
            "raid_strength": row.get("raid_strength"),
            "h1_reaction_diagnostic": row.get("h1_reaction"),
            "h1_vc": row.get("h1_vc"),
            "h1_vc_strength": row.get("h1_vc_strength"),
            "vc_zone_test": row.get("vc_zone_test"),
            "vc_zone_test_strength": row.get("vc_zone_test_strength"),
            "m5_bos": row.get("m5_bos"),
            "m5_bos_strength": row.get("m5_bos_strength"),
        },
        "planned_structure": {
            "entry_time": row.get("planned_entry_time"),
            "entry": row.get("planned_entry"),
            "stop": row.get("planned_stop"),
            "target": row.get("planned_target"),
            "target_timeframe": row.get("target_timeframe"),
            "target_source": row.get("target_source"),
            "planned_rr": row.get("planned_rr"),
        },
        "quality": {
            "score": row.get("quality_score"),
            "state": row.get("quality_state"),
        },
        "event_risk": {
            "blocked": row.get("event_blocked"),
            "risk_multiplier": row.get("event_risk_multiplier"),
        },
        "reasons": list(row.get("reasons") or []),
        "human_review": {
            "context_correct": None,
            "dealing_range_correct": None,
            "poi_correct": None,
            "h1_confirmation_correct": None,
            "m5_bos_correct": None,
            "next_15m_execution_correct": None,
            "structural_stop_correct": None,
            "timeframe_target_correct": None,
            "verdict": "UNREVIEWED",
            "notes": "",
        },
    }
    assert_no_outcome_fields(packet)
    return packet


def build_queue(payload: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    assert_no_outcome_fields(payload)
    if payload.get("mode") != "NO_PNL_NO_FUTURE_OUTCOME":
        raise RuntimeError("unexpected recognition mode")
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise RuntimeError("candidates list missing")
    ordered = balanced_review_order(rows)
    fingerprints = [case_fingerprint(row) for row in ordered]
    cluster_sizes = Counter(fingerprints)
    cluster_seen: Counter[str] = Counter()
    packets_dir = out_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    queue_rows: list[dict[str, Any]] = []
    for index, (row, fingerprint) in enumerate(zip(ordered, fingerprints), start=1):
        cluster_seen[fingerprint] += 1
        occurrence = cluster_seen[fingerprint]
        packet_name = f"{index:04d}_{row.get('symbol')}_{row.get('side')}_{row.get('setup_state')}.json"
        packet = packet_payload(row, index, fingerprint, cluster_sizes[fingerprint], occurrence)
        (packets_dir / packet_name).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        poi = row.get("poi") or {}
        queue_rows.append(
            {
                "review_index": index,
                "timestamp": row.get("timestamp"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "setup_state": row.get("setup_state"),
                "stage_rank": row.get("stage_rank"),
                "case_fingerprint": fingerprint,
                "cluster_size": cluster_sizes[fingerprint],
                "cluster_occurrence": occurrence,
                "scenario": row.get("scenario"),
                "daily_state": row.get("daily_state"),
                "h4_state": row.get("h4_state"),
                "poi_timeframe": poi.get("timeframe"),
                "poi_kind": poi.get("kind"),
                "poi_source": poi.get("source"),
                "h1_raid": row.get("h1_raid"),
                "h1_vc": row.get("h1_vc"),
                "vc_zone_test": row.get("vc_zone_test"),
                "m5_bos": row.get("m5_bos"),
                "entry_ready": row.get("entry_ready"),
                "target_timeframe": row.get("target_timeframe"),
                "quality_state": row.get("quality_state"),
                "reasons": "|".join(row.get("reasons") or []),
                "packet_file": f"packets/{packet_name}",
            }
        )
    with (out_dir / "recognition_review_queue.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue_rows)
    queue_json = {
        "study_id": "SMOKE_MTF_V2_RECOGNITION_REVIEW_QUEUE",
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "source_selection_rule": payload.get("selection_rule"),
        "review_order_rule": "round-robin across setup_state, side and symbol; no rows dropped",
        "row_count": len(queue_rows),
        "unique_case_fingerprints": len(cluster_sizes),
        "repeated_snapshot_rows": sum(size - 1 for size in cluster_sizes.values()),
        "cluster_sizes": dict(sorted(cluster_sizes.items())),
        "rows": queue_rows,
    }
    assert_no_outcome_fields(queue_json)
    (out_dir / "recognition_review_queue.json").write_text(json.dumps(queue_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return queue_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Build balanced SMOKE MTF V2 recognition review queue")
    parser.add_argument("--candidates-json", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.candidates_json).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    queue = build_queue(payload, out)
    print(
        f"Built {queue['row_count']} review packets across "
        f"{queue['unique_case_fingerprints']} structural fingerprints"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
