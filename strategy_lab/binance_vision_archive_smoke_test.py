#!/usr/bin/env python3
"""Smoke test for Binance Vision USD-M archive merging."""

from __future__ import annotations

import csv
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from strategy_lab.binance_vision_archive import merge_archives


def epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def write_zip(path: Path, member: str, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(",".join(str(value) for value in row) for row in rows) + "\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(member, payload)


def candle(ts: int, open_price: float) -> list[object]:
    return [ts, open_price, open_price + 2, open_price - 1, open_price + 1, 1000]


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archives = root / "archives"
        out_csv = root / "candles.csv"
        summary_json = root / "summary.json"
        t0 = epoch_ms("2026-01-01T00:00:00")
        t1 = epoch_ms("2026-01-01T00:15:00")
        t2 = epoch_ms("2026-01-01T00:30:00")

        write_zip(
            archives / "data/futures/um/monthly/klines/AAAUSDT/15m/AAAUSDT-15m-2026-01.zip",
            "AAAUSDT-15m-2026-01.csv",
            [["open_time", "open", "high", "low", "close", "volume"], candle(t0, 100), candle(t1, 101)],
        )
        write_zip(
            archives / "data/futures/um/daily/klines/AAAUSDT/15m/AAAUSDT-15m-2026-01-01.zip",
            "AAAUSDT-15m-2026-01-01.csv",
            [candle(t1, 101), candle(t2, 102)],
        )
        # Microsecond timestamps are normalized to milliseconds.
        write_zip(
            archives / "data/futures/um/daily/klines/BBBUSDT/15m/BBBUSDT-15m-2026-01-01.zip",
            "BBBUSDT-15m-2026-01-01.csv",
            [candle(t0 * 1000, 200), candle(t1 * 1000, 201)],
        )
        # Unrequested symbol must not leak into the merged dataset.
        write_zip(
            archives / "data/futures/um/daily/klines/CCCUSDT/15m/CCCUSDT-15m-2026-01-01.zip",
            "CCCUSDT-15m-2026-01-01.csv",
            [candle(t0, 300)],
        )

        summary = merge_archives(
            input_dir=archives,
            out_csv=out_csv,
            symbols=["AAAUSDT", "BBBUSDT"],
            interval="15m",
            start_date="2026-01-01",
            end_date="2026-01-01",
            summary_json=summary_json,
            min_coverage=1.0,
            now=datetime(2026, 1, 2, 0, 0),
        )
        with out_csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        assert summary.status == "OK"
        assert summary.symbols_loaded == 2
        assert summary.rows_written == 5
        assert summary.duplicate_rows == 1
        assert {row["symbol"] for row in rows} == {"AAAUSDT", "BBBUSDT"}
        assert len({(row["symbol"], row["time"]) for row in rows}) == 5
        assert rows[0]["time"] == "2026-01-01T00:00:00"
        assert summary_json.exists()
    print("binance_vision_archive_smoke_test: PASS")


if __name__ == "__main__":
    main()
