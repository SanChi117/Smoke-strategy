#!/usr/bin/env python3
"""Paper mode review report.

Reads paper_positions.csv and creates a compact manual-review report.

Research only. No live trading. No exchange calls.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PaperReviewRow:
    paper_id: str
    symbol: str
    side: str
    close_reason: str
    pnl_pct: float
    setup_type: str
    risk_grade: str
    review_status: str
    review_reason: str


@dataclass(frozen=True)
class PaperReviewSummary:
    positions: int
    approved: int
    watch: int
    rejected: int
    avg_pnl_pct: float
    status: str


def read_rows(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def review_position(row: dict[str, str]) -> PaperReviewRow:
    pnl = to_float(row.get("pnl_pct"))
    close_reason = str(row.get("close_reason", "")).strip().lower()
    risk_grade = str(row.get("risk_grade", "")).strip().upper()
    reasons: list[str] = []
    status = "APPROVED"

    if pnl < 0:
        status = "REJECTED"
        reasons.append("negative_pnl")
    elif close_reason in {"stop_loss", "sl"}:
        status = "REJECTED"
        reasons.append("stop_loss_close")
    elif pnl == 0:
        status = "WATCH"
        reasons.append("flat_pnl")

    if risk_grade in {"C", "D", "SKIP"}:
        status = "REJECTED" if status == "REJECTED" else "WATCH"
        reasons.append("weak_risk_grade")
    elif not risk_grade:
        if status == "APPROVED":
            status = "WATCH"
        reasons.append("missing_risk_grade")

    if close_reason in {"time_stop", "timeout"}:
        if status == "APPROVED":
            status = "WATCH"
        reasons.append("time_stop_close")

    if not reasons:
        reasons.append("paper_trade_passed_basic_review")

    return PaperReviewRow(
        paper_id=str(row.get("paper_id", "")),
        symbol=str(row.get("symbol", "")),
        side=str(row.get("side", "")),
        close_reason=str(row.get("close_reason", "")),
        pnl_pct=round(pnl, 6),
        setup_type=str(row.get("setup_type", "")),
        risk_grade=str(row.get("risk_grade", "")),
        review_status=status,
        review_reason=";".join(reasons),
    )


def write_dict_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]


def run_paper_review(paper_positions_csv: str | Path, out_dir: str | Path) -> PaperReviewSummary:
    rows = read_rows(paper_positions_csv)
    reviewed = [review_position(row) for row in rows]
    approved = sum(1 for row in reviewed if row.review_status == "APPROVED")
    watch = sum(1 for row in reviewed if row.review_status == "WATCH")
    rejected = sum(1 for row in reviewed if row.review_status == "REJECTED")
    avg_pnl = round(sum(row.pnl_pct for row in reviewed) / len(reviewed), 6) if reviewed else 0.0
    status = "EMPTY" if not reviewed else "PASS" if rejected == 0 and watch == 0 else "WATCH" if rejected == 0 else "REVIEW"
    summary = PaperReviewSummary(
        positions=len(reviewed),
        approved=approved,
        watch=watch,
        rejected=rejected,
        avg_pnl_pct=avg_pnl,
        status=status,
    )
    out = Path(out_dir)
    write_dict_csv(out / "paper_review.csv", rows_as_dicts(reviewed))
    write_dict_csv(out / "paper_review_summary.csv", rows_as_dicts([summary]))
    return summary
