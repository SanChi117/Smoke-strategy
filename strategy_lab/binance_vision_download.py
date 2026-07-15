#!/usr/bin/env python3
"""Download official Binance Vision USD-M Futures kline archives.

The planner uses monthly ZIPs for completed calendar months and daily ZIPs only
for the final incomplete month. This avoids thousands of duplicate daily files
while preserving exact date filtering in the merge stage.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from strategy_lab.binance_vision_archive import parse_date, parse_symbols


BASE_URL = "https://data.binance.vision/data/futures/um"


@dataclass(frozen=True)
class ArchiveRequest:
    symbol: str
    interval: str
    period: str
    filename: str
    url: str
    checksum_url: str
    relative_path: str


@dataclass(frozen=True)
class DownloadSummary:
    source: str
    start_date: str
    end_date: str
    interval: str
    symbols_requested: int
    archive_requests: int
    archives_downloaded: int
    archives_reused: int
    archives_missing: int
    archives_failed: int
    checksum_verified: int
    zip_verified: int
    bytes_downloaded: int
    missing_examples: tuple[str, ...]
    failed_examples: tuple[str, ...]
    status: str


def next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def month_starts(start_day: date, end_day: date) -> list[date]:
    current = start_day.replace(day=1)
    out: list[date] = []
    while current <= end_day:
        out.append(current)
        current = next_month(current)
    return out


def build_archive_requests(
    symbols: Iterable[str],
    interval: str,
    start_date: str | date,
    end_date: str | date,
) -> list[ArchiveRequest]:
    requested = parse_symbols(symbols)
    start_day = parse_date(start_date)
    end_day = parse_date(end_date)
    if end_day < start_day:
        raise ValueError("end_date must not be earlier than start_date")

    periods: list[tuple[str, str]] = []
    for month_start in month_starts(start_day, end_day):
        month_end = next_month(month_start) - timedelta(days=1)
        if month_end <= end_day:
            periods.append(("monthly", month_start.strftime("%Y-%m")))
            continue
        current = max(start_day, month_start)
        while current <= end_day:
            periods.append(("daily", current.isoformat()))
            current += timedelta(days=1)

    requests: list[ArchiveRequest] = []
    for symbol in requested:
        for cadence, period in periods:
            filename = f"{symbol}-{interval}-{period}.zip"
            url = f"{BASE_URL}/{cadence}/klines/{symbol}/{interval}/{filename}"
            requests.append(ArchiveRequest(
                symbol=symbol,
                interval=interval,
                period=period,
                filename=filename,
                url=url,
                checksum_url=url + ".CHECKSUM",
                relative_path=f"{cadence}/klines/{symbol}/{interval}/{filename}",
            ))
    return requests


def request_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SmokeStrategyLab/binance-vision"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official host
        return response.read()


def expected_checksum(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    token = text.split()[0].strip().lower()
    if len(token) == 64 and all(ch in "0123456789abcdef" for ch in token):
        return token
    return None


def valid_existing_zip(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as bundle:
            return bundle.testzip() is None and any(name.lower().endswith(".csv") for name in bundle.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def download_one(
    item: ArchiveRequest,
    out_dir: Path,
    retries: int,
    timeout: int,
) -> dict[str, object]:
    target = out_dir / item.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if valid_existing_zip(target):
        return {"status": "reused", "request": item, "bytes": 0, "checksum": False, "zip": True}

    last_error = ""
    for attempt in range(max(1, retries + 1)):
        temp = target.with_suffix(target.suffix + f".part-{os.getpid()}")
        try:
            payload = request_bytes(item.url, timeout=timeout)
            actual = hashlib.sha256(payload).hexdigest()
            checksum_ok = False
            try:
                checksum = expected_checksum(request_bytes(item.checksum_url, timeout=timeout))
                checksum_ok = checksum is not None and checksum == actual
                if checksum is not None and not checksum_ok:
                    raise RuntimeError("SHA256 checksum mismatch")
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            temp.write_bytes(payload)
            if not valid_existing_zip(temp):
                raise RuntimeError("downloaded file is not a valid kline ZIP")
            temp.replace(target)
            return {
                "status": "downloaded",
                "request": item,
                "bytes": len(payload),
                "checksum": checksum_ok,
                "zip": True,
            }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                temp.unlink(missing_ok=True)
                return {"status": "missing", "request": item, "bytes": 0, "checksum": False, "zip": False}
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            last_error = str(exc)
        finally:
            temp.unlink(missing_ok=True)
        if attempt < retries:
            time.sleep(min(8.0, 1.5 * (attempt + 1)))
    return {
        "status": "failed",
        "request": item,
        "bytes": 0,
        "checksum": False,
        "zip": False,
        "error": last_error,
    }


def download_archives(
    symbols: Iterable[str],
    interval: str,
    start_date: str | date,
    end_date: str | date,
    out_dir: str | Path,
    summary_json: str | Path | None = None,
    workers: int = 8,
    retries: int = 2,
    timeout: int = 30,
) -> DownloadSummary:
    requested = parse_symbols(symbols)
    requests = build_archive_requests(requested, interval, start_date, end_date)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(download_one, item, destination, retries, timeout): item
            for item in requests
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # defensive: preserve a complete audit summary
                result = {"status": "failed", "request": item, "bytes": 0, "error": str(exc)}
            results.append(result)
            status = result.get("status")
            if status in {"failed", "missing"}:
                print(f"{status.upper()}: {item.filename} {result.get('error', '')}", flush=True)

    counts = {name: sum(1 for row in results if row.get("status") == name) for name in ("downloaded", "reused", "missing", "failed")}
    missing = [str(row["request"].filename) for row in results if row.get("status") == "missing"]
    failed = [f"{row['request'].filename}: {row.get('error', '')}" for row in results if row.get("status") == "failed"]
    usable = counts["downloaded"] + counts["reused"]
    status = "OK" if usable > 0 and counts["failed"] == 0 else "PARTIAL" if usable > 0 else "FAILED"
    summary = DownloadSummary(
        source="BINANCE_VISION_USDM_FUTURES_ARCHIVE",
        start_date=parse_date(start_date).isoformat(),
        end_date=parse_date(end_date).isoformat(),
        interval=interval,
        symbols_requested=len(requested),
        archive_requests=len(requests),
        archives_downloaded=counts["downloaded"],
        archives_reused=counts["reused"],
        archives_missing=counts["missing"],
        archives_failed=counts["failed"],
        checksum_verified=sum(1 for row in results if row.get("checksum")),
        zip_verified=sum(1 for row in results if row.get("zip")),
        bytes_downloaded=sum(int(row.get("bytes", 0)) for row in results),
        missing_examples=tuple(missing[:20]),
        failed_examples=tuple(failed[:20]),
        status=status,
    )
    if summary_json is not None:
        path = Path(summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if status == "FAILED":
        raise RuntimeError("No Binance Vision USD-M Futures archives were downloaded")
    return summary
