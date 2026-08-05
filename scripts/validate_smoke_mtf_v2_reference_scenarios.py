#!/usr/bin/env python3
"""Validate the frozen semantic reference set and write an audit report."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from strategy_lab.mtf_reference_validation import load_and_validate_reference


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SMOKE MTF V2 reference scenarios")
    parser.add_argument(
        "--reference",
        default="research/smoke_mtf_v2_reference_scenarios.json",
    )
    parser.add_argument(
        "--out",
        default="results/smoke_mtf_v2_reference_validation/report.json",
    )
    args = parser.parse_args()

    report = load_and_validate_reference(args.reference)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    payload["ok"] = report.ok
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report.ok:
        for error in report.errors:
            print(f"ERROR: {error}")
        return 1
    print(
        f"Reference set OK: {report.scenario_count} scenarios, "
        f"{report.positive_count} positive, {report.blocked_count} blocked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
