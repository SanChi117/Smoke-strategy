#!/usr/bin/env python3
"""Validation helpers for Smoke Strategy Lab.

These checks make the research pipeline harder to break silently. They are not
proof of profitability; they verify that reports are structurally valid and
that the pipeline is producing analyzable outputs.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    check: str
    message: str


@dataclass(frozen=True)
class ValidationSummary:
    checks: int
    errors: int
    warnings: int
    status: str


def count_rows(path: str | Path) -> int:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.DictReader(f)))


def read_first_row(path: str | Path) -> dict[str, str]:
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return next(reader, {})


def validate_pipeline_outputs(out_dir: str | Path) -> tuple[ValidationSummary, list[ValidationIssue]]:
    out = Path(out_dir)
    issues: list[ValidationIssue] = []

    required_files = [
        "pipeline_summary.csv",
        "pipeline_universe_ranking.csv",
        "pipeline_decisions.csv",
        "pipeline_risk_diagnostics.csv",
        "pipeline_risk_policy.csv",
    ]

    for name in required_files:
        path = out / name
        if not path.exists():
            issues.append(ValidationIssue("error", f"exists:{name}", f"Missing required report: {name}"))
        elif count_rows(path) <= 0:
            issues.append(ValidationIssue("error", f"non_empty:{name}", f"Report is empty: {name}"))

    summary_path = out / "pipeline_summary.csv"
    decisions_path = out / "pipeline_decisions.csv"
    if summary_path.exists() and count_rows(summary_path) == 1:
        summary = read_first_row(summary_path)
        candidates = int(float(summary.get("candidates", "0") or 0))
        allowed = int(float(summary.get("allowed_candidates", "0") or 0))
        executed = int(float(summary.get("executed_trades", "0") or 0))
        final_cash = float(summary.get("final_cash", "0") or 0)
        avg_risk = float(summary.get("avg_risk_pct", "0") or 0)
        if candidates <= 0:
            issues.append(ValidationIssue("error", "summary:candidates", "Pipeline produced zero candidates."))
        if allowed <= 0:
            issues.append(ValidationIssue("warning", "summary:allowed", "Pipeline produced zero allowed candidates."))
        if executed <= 0:
            issues.append(ValidationIssue("warning", "summary:executed", "Pipeline executed zero trades."))
        if final_cash <= 0:
            issues.append(ValidationIssue("error", "summary:final_cash", "Final cash is not positive."))
        if allowed > 0 and avg_risk <= 0:
            issues.append(ValidationIssue("error", "summary:avg_risk", "Allowed trades exist but average risk is zero."))
        if decisions_path.exists() and count_rows(decisions_path) != candidates:
            issues.append(ValidationIssue("error", "decisions:coverage", "Decision rows do not match candidate count."))

    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    checks = len(required_files) + 6
    status = "FAIL" if errors else "WARN" if warnings else "OK"
    return ValidationSummary(checks=checks, errors=errors, warnings=warnings, status=status), issues


def write_validation_report(out_dir: str | Path) -> ValidationSummary:
    out = Path(out_dir)
    summary, issues = validate_pipeline_outputs(out)
    summary_path = out / "pipeline_validation_summary.csv"
    issues_path = out / "pipeline_validation_issues.csv"

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(summary).keys()))
        writer.writeheader()
        writer.writerow(asdict(summary))

    issue_rows = [asdict(i) for i in issues]
    with issues_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["level", "check", "message"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(issue_rows)

    return summary
