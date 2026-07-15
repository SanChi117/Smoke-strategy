#!/usr/bin/env python3
"""Smoke test for Binance Vision archive planning and verification."""

from __future__ import annotations

import hashlib
import io
import tempfile
import zipfile
from pathlib import Path

from strategy_lab import binance_vision_download as download


def sample_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "AAAUSDT-15m-2026-01.csv",
            "1767225600000,100,102,99,101,1000\n",
        )
    return buffer.getvalue()


def main() -> None:
    planned = download.build_archive_requests(
        symbols=["AAAUSDT", "BBBUSDT"],
        interval="15m",
        start_date="2025-12-20",
        end_date="2026-02-03",
    )
    assert len(planned) == 10  # two completed months + three daily files, per symbol
    assert sum("/monthly/" in item.url for item in planned) == 4
    assert sum("/daily/" in item.url for item in planned) == 6
    assert all("/data/futures/um/" in item.url for item in planned)

    payload = sample_zip()
    checksum = hashlib.sha256(payload).hexdigest().encode() + b"  AAAUSDT-15m-2026-01.zip\n"
    original = download.request_bytes

    def fake_request(url: str, timeout: int = 30) -> bytes:
        del timeout
        return checksum if url.endswith(".CHECKSUM") else payload

    try:
        download.request_bytes = fake_request
        with tempfile.TemporaryDirectory() as td:
            item = download.build_archive_requests(
                symbols=["AAAUSDT"],
                interval="15m",
                start_date="2026-01-01",
                end_date="2026-01-31",
            )[0]
            first = download.download_one(item, Path(td), retries=0, timeout=5)
            second = download.download_one(item, Path(td), retries=0, timeout=5)
            assert first["status"] == "downloaded"
            assert first["checksum"] is True
            assert first["zip"] is True
            assert second["status"] == "reused"
    finally:
        download.request_bytes = original
    print("binance_vision_download_smoke_test: PASS")


if __name__ == "__main__":
    main()
