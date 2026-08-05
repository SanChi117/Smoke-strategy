#!/usr/bin/env python3
"""Aggregate 100 outcome-blind SMOKE MTF funnel partitions."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median

from strategy_lab.mtf_no_pnl_funnel_v1 import STAGES, assert_no_outcome_fields, transition_rates


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(len(ordered) - 1, low + 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 10) if ordered else None,
        "p25": round(_percentile(ordered, 0.25), 10) if ordered else None,
        "median": round(median(ordered), 10) if ordered else None,
        "p75": round(_percentile(ordered, 0.75), 10) if ordered else None,
        "p90": round(_percentile(ordered, 0.90), 10) if ordered else None,
        "max": round(ordered[-1], 10) if ordered else None,
    }


def _merge_nested_counts(parts: list[dict], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for part in parts:
        counter.update({str(key): int(value) for key, value in part.get(field, {}).items()})
    return dict(sorted(counter.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--expected-parts", type=int, default=100)
    args = parser.parse_args()

    files = sorted(Path(args.parts_root).rglob("funnel_part.json"))
    if len(files) != args.expected_parts:
        raise AssertionError(f"expected {args.expected_parts} funnel parts, found {len(files)}")
    parts = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    for part in parts:
        assert_no_outcome_fields(part)
        if part.get("study_id") != "SMOKE_MTF_V3_NO_PNL_FUNNEL_V1":
            raise AssertionError("unexpected study id")
        if part.get("outcome_fields_excluded") is not True:
            raise AssertionError("part did not affirm outcome exclusion")

    identities = {(part["symbol"], part["side"], int(part["fold"])) for part in parts}
    if len(identities) != args.expected_parts:
        raise AssertionError("duplicate or missing symbol/side/fold identity")

    stage_counts = Counter()
    monthly: dict[str, Counter[str]] = defaultdict(Counter)
    fingerprint_counts = Counter()
    geometry: list[dict] = []
    transition_timing_raw: dict[str, dict[str, float | int]] = {}

    for part in parts:
        stage_counts.update({stage: int(part["stage_counts"].get(stage, 0)) for stage in STAGES})
        for month, values in part.get("monthly_stage_counts", {}).items():
            monthly[month].update({stage: int(values.get(stage, 0)) for stage in STAGES})
        fingerprint_counts.update({str(key): int(value) for key, value in part.get("structural_fingerprint_counts", {}).items()})
        geometry.extend(part.get("structural_geometry_records", []))
        for key, values in part.get("setup_state_transition_timing", {}).items():
            target = transition_timing_raw.setdefault(key, {"count": 0, "total_minutes": 0.0, "max_minutes": 0.0})
            target["count"] = int(target["count"]) + int(values.get("count", 0))
            target["total_minutes"] = float(target["total_minutes"]) + float(values.get("total_minutes", 0.0))
            target["max_minutes"] = max(float(target["max_minutes"]), float(values.get("max_minutes", 0.0)))

    transition_timing = {}
    for key, values in sorted(transition_timing_raw.items()):
        count = int(values["count"])
        transition_timing[key] = {
            "count": count,
            "total_minutes": round(float(values["total_minutes"]), 4),
            "average_minutes": round(float(values["total_minutes"]) / count, 4) if count else 0.0,
            "max_minutes": round(float(values["max_minutes"]), 4),
        }

    stop_distances = [float(row["structural_stop_distance_fraction"]) for row in geometry if "structural_stop_distance_fraction" in row]
    fta_distances = [float(row["active_fta_distance_fraction"]) for row in geometry if "active_fta_distance_fraction" in row]
    structural_rr = [float(row["structural_rr"]) for row in geometry if "structural_rr" in row]
    rates = transition_rates(stage_counts)
    valid_rates = [(key, float(value["rate"])) for key, value in rates.items() if int(value["from_count"]) > 0]
    primary_bottleneck = min(valid_rates, key=lambda item: item[1]) if valid_rates else ("none", 0.0)

    unique_fingerprints = len(fingerprint_counts)
    repeated_snapshots = sum(max(0, count - 1) for count in fingerprint_counts.values())
    top_fingerprints = [
        {"fingerprint": key, "count": count}
        for key, count in fingerprint_counts.most_common(25)
    ]

    result = {
        "study_id": "SMOKE_MTF_V3_NO_PNL_FUNNEL_V1",
        "status": "COMPLETE",
        "source_candidate": {
            "recognition_freeze_sha": "492eee9fdba5993b7f518e9a1ff38576e8b14285",
            "development_run_id": 29906237656,
            "development_candidate_closed": True,
        },
        "coverage": {
            "parts": len(parts),
            "symbols": sorted({part["symbol"] for part in parts}),
            "sides": sorted({part["side"] for part in parts}),
            "folds": sorted({int(part["fold"]) for part in parts}),
            "evaluated_15m_bars": sum(int(part["evaluated_15m_bars"]) for part in parts),
        },
        "funnel_stage_counts": {stage: int(stage_counts.get(stage, 0)) for stage in STAGES},
        "funnel_transition_rates": rates,
        "primary_structural_bottleneck": {
            "transition": primary_bottleneck[0],
            "rate": round(primary_bottleneck[1], 8),
        },
        "setup_state_counts": _merge_nested_counts(parts, "setup_state_counts"),
        "route_counts": _merge_nested_counts(parts, "route_counts"),
        "rejection_reason_counts": _merge_nested_counts(parts, "rejection_reason_counts"),
        "context_scenario_counts": _merge_nested_counts(parts, "context_scenario_counts"),
        "poi_timeframe_counts": _merge_nested_counts(parts, "poi_timeframe_counts"),
        "poi_source_counts": _merge_nested_counts(parts, "poi_source_counts"),
        "monthly_funnel_stage_counts": {
            month: {stage: int(values.get(stage, 0)) for stage in STAGES}
            for month, values in sorted(monthly.items())
        },
        "setup_state_transition_counts": _merge_nested_counts(parts, "setup_state_transition_counts"),
        "setup_state_transition_timing": transition_timing,
        "pre_outcome_structural_geometry": {
            "records": len(geometry),
            "structural_stop_distance_fraction": _distribution(stop_distances),
            "active_fta_distance_fraction": _distribution(fta_distances),
            "structural_rr": _distribution(structural_rr),
        },
        "structural_fingerprints": {
            "unique": unique_fingerprints,
            "repeated_snapshots": repeated_snapshots,
            "top": top_fingerprints,
        },
        "outcome_fields_excluded": True,
        "allowed_next_action": "DESIGN_AT_MOST_ONE_MATERIALLY_NEW_V3_CANDIDATE_FROM_CAUSAL_FUNNEL_ONLY",
        "forbidden_next_actions": ["OUTCOME_BASED_TUNING", "HOLDOUT", "VPS", "PAPER", "LIVE"],
    }
    assert_no_outcome_fields(result)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "funnel_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# SMOKE MTF V3 — No-PnL Funnel Audit",
        "",
        "Status: `COMPLETE`",
        "",
        f"- Parts: **{len(parts)}**",
        f"- Evaluated 15m side snapshots: **{result['coverage']['evaluated_15m_bars']}**",
        f"- Primary bottleneck: **{primary_bottleneck[0]}** at **{primary_bottleneck[1]:.4%}**",
        f"- ENTRY_READY: **{stage_counts.get('ENTRY_READY', 0)}**",
        f"- Unique structural fingerprints: **{unique_fingerprints}**",
        f"- Repeated structural snapshots: **{repeated_snapshots}**",
        "",
        "## Sequential funnel",
        "",
    ]
    for stage in STAGES:
        lines.append(f"- `{stage}`: **{stage_counts.get(stage, 0)}**")
    lines.extend([
        "",
        "Outcome fields and future price results were excluded. This report may only support one materially new preregistered V3 design.",
    ])
    (out / "FUNNEL_RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "primary_bottleneck": result["primary_structural_bottleneck"], "entry_ready": stage_counts.get("ENTRY_READY", 0)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
