#!/usr/bin/env python3
"""Merge Binance Vision USD-M funding-rate ZIP archives into canonical CSV."""
from __future__ import annotations

import argparse
import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def parse_time(value: str) -> datetime:
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    if number > 10_000_000_000:
        number /= 1000.0
    return datetime.utcfromtimestamp(number)


def detect_columns(header: list[str] | None, row: list[str]) -> tuple[int, int]:
    if header:
        normalized = [item.strip().lower() for item in header]
        time_names = ("calc_time", "fundingtime", "funding_time", "timestamp", "time")
        rate_names = ("last_funding_rate", "fundingrate", "funding_rate", "rate")
        time_index = next((normalized.index(name) for name in time_names if name in normalized), 0)
        rate_index = next((normalized.index(name) for name in rate_names if name in normalized), len(row) - 1)
        return time_index, rate_index
    return 0, len(row) - 1


def looks_header(row: list[str]) -> bool:
    joined = ",".join(row).lower()
    return any(token in joined for token in ("time", "rate", "interval"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end-exclusive", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    start = datetime.fromisoformat(args.start.replace("Z", ""))
    end = datetime.fromisoformat(args.end_exclusive.replace("Z", ""))
    values: dict[datetime, float] = {}
    archives = sorted(Path(args.input_dir).rglob("*.zip"))
    malformed = 0
    for archive in archives:
        with zipfile.ZipFile(archive) as bundle:
            names = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
            for name in names:
                lines = bundle.read(name).decode("utf-8-sig", errors="replace").splitlines()
                rows = list(csv.reader(lines))
                if not rows:
                    continue
                header = rows[0] if looks_header(rows[0]) else None
                data = rows[1:] if header else rows
                for row in data:
                    if not row:
                        continue
                    try:
                        time_index, rate_index = detect_columns(header, row)
                        at = parse_time(row[time_index])
                        rate = float(row[rate_index])
                    except (ValueError, IndexError):
                        malformed += 1
                        continue
                    if start <= at < end:
                        values[at] = rate
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "time", "rate"])
        writer.writeheader()
        for at, rate in sorted(values.items()):
            writer.writerow({"symbol": symbol, "time": at.isoformat(timespec="seconds"), "rate": f"{rate:.12g}"})
    ordered = sorted(values)
    gaps = [
        (right - left).total_seconds() / 3600.0
        for left, right in zip(ordered, ordered[1:])
        if (right - left).total_seconds() > 16 * 3600
    ]
    summary = {
        "source": "BINANCE_VISION_USDM_FUNDING_RATE",
        "symbol": symbol,
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "archives": len(archives),
        "funding_rows": len(values),
        "first_time": ordered[0].isoformat() if ordered else None,
        "last_time": ordered[-1].isoformat() if ordered else None,
        "malformed_rows": malformed,
        "gaps_over_16h": len(gaps),
        "max_gap_hours": max(gaps) if gaps else 0.0,
        "status": "OK" if values and malformed == 0 else "INCOMPLETE",
    }
    Path(args.summary_json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["status"] != "OK":
        raise RuntimeError("funding merge incomplete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
