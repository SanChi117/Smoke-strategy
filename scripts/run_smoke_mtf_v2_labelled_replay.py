#!/usr/bin/env python3
"""Run SMOKE MTF V2 recognition against human-labelled candle examples."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategy_lab.market_data import read_candles_csv, validate_candles
from strategy_lab.mtf_labelled_replay import report_as_dict, run_labelled_replay


def main() -> int:
    parser = argparse.ArgumentParser(description="Run labelled SMOKE MTF V2 replay")
    parser.add_argument("--candles", required=True, help="Closed 5m candle CSV")
    parser.add_argument("--labels", required=True, help="Frozen labelled case JSON")
    parser.add_argument("--out", required=True, help="Replay report JSON")
    args = parser.parse_args()

    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    if not isinstance(labels, dict):
        raise ValueError("labels root must be an object")

    report = run_labelled_replay(candles, labels)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report_as_dict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Labelled replay: {report.passed_count}/{report.case_count} passed; "
        f"failed={report.failed_count}"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
