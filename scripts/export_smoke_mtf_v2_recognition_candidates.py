#!/usr/bin/env python3
"""Export real-history SMOKE MTF V2 states without future outcomes or PnL."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_recognition_export_v2 import export_recognition_candidates


def write_compact_csv(path: Path, candidates: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
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
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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
    parser = argparse.ArgumentParser(description="Export no-PnL SMOKE MTF V2 recognition cases")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--scan-start", required=True)
    parser.add_argument("--scan-end", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--per-group", type=int, default=4)
    args = parser.parse_args()

    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    result = export_recognition_candidates(
        candles,
        parse_dt(args.scan_start),
        parse_dt(args.scan_end),
        max(1, args.per_group),
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "recognition_candidates.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {key: value for key, value in result.items() if key != "candidates"}
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_compact_csv(out / "recognition_candidates.csv", result["candidates"])
    print(
        f"No-PnL recognition export: {result['selected_snapshots']} selected from "
        f"{result['qualifying_snapshots']} qualifying snapshots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
