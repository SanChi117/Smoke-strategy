#!/usr/bin/env python3
"""Download official Binance Vision USD-M monthly funding-rate archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path


BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


def parse_month(value: str) -> date:
    return date.fromisoformat(value + "-01")


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


def months(start: str, end_exclusive: str) -> list[str]:
    cursor = parse_month(start)
    end = parse_month(end_exclusive)
    out = []
    while cursor < end:
        out.append(cursor.strftime("%Y-%m"))
        cursor = next_month(cursor)
    return out


def request_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SmokeStrategyLab/funding"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def checksum(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="replace").strip()
    token = text.split()[0].lower() if text else ""
    return token if len(token) == 64 else None


def valid_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as bundle:
            return bundle.testzip() is None and any(name.lower().endswith(".csv") for name in bundle.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def download_one(symbol: str, month: str, out: Path, retries: int, timeout: int) -> dict:
    filename = f"{symbol}-fundingRate-{month}.zip"
    url = f"{BASE}/{symbol}/{filename}"
    target = out / symbol / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and valid_zip(target):
        return {"symbol": symbol, "month": month, "status": "reused", "bytes": 0}
    last_error = ""
    for attempt in range(retries + 1):
        temp = target.with_suffix(target.suffix + f".part-{os.getpid()}")
        try:
            payload = request_bytes(url, timeout)
            actual = hashlib.sha256(payload).hexdigest()
            try:
                expected = checksum(request_bytes(url + ".CHECKSUM", timeout))
                if expected and expected != actual:
                    raise RuntimeError("checksum mismatch")
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            temp.write_bytes(payload)
            if not valid_zip(temp):
                raise RuntimeError("invalid funding ZIP")
            temp.replace(target)
            return {"symbol": symbol, "month": month, "status": "downloaded", "bytes": len(payload)}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                temp.unlink(missing_ok=True)
                return {"symbol": symbol, "month": month, "status": "missing", "bytes": 0}
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        finally:
            temp.unlink(missing_ok=True)
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    return {"symbol": symbol, "month": month, "status": "failed", "bytes": 0, "error": last_error}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month-exclusive", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    periods = months(args.start_month, args.end_month_exclusive)
    out = Path(args.out_dir)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [
            pool.submit(download_one, symbol, month, out, args.retries, args.timeout)
            for month in periods
        ]
        rows = [future.result() for future in as_completed(futures)]
    rows.sort(key=lambda row: row["month"])
    counts = {
        status: sum(1 for row in rows if row["status"] == status)
        for status in ("downloaded", "reused", "missing", "failed")
    }
    summary = {
        "source": "BINANCE_VISION_USDM_MONTHLY_FUNDING_RATE",
        "symbol": symbol,
        "start_month": args.start_month,
        "end_month_exclusive": args.end_month_exclusive,
        "requested_months": len(periods),
        **{f"{key}_months": value for key, value in counts.items()},
        "bytes_downloaded": sum(int(row.get("bytes", 0)) for row in rows),
        "status": "OK" if counts["missing"] == 0 and counts["failed"] == 0 else "INCOMPLETE",
        "rows": rows,
    }
    target = Path(args.summary_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["status"] != "OK":
        raise RuntimeError("funding archive coverage incomplete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
