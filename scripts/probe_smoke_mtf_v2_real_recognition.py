#!/usr/bin/env python3
"""Probe one frozen SMOKE MTF V2 GitHub Actions run and publish a PR status.

This script changes no trading rule and reads only GitHub run metadata/artifacts.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

MARKER = "<!-- smoke-mtf-v2-real-recognition-status -->"
FORBIDDEN = ("pnl", "future_return", "realized_return", "tp_hit", "sl_hit", "mfe", "mae")


def _request(path_or_url: str, method: str = "GET", payload: Any | None = None) -> Any:
    token = os.environ["GITHUB_TOKEN"]
    url = path_or_url if path_or_url.startswith("http") else f"https://api.github.com{path_or_url}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return json.loads(raw.decode("utf-8"))
        return raw


def _walk_forbidden(value: Any, path: str = "root") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lower = str(key).lower()
            for token in FORBIDDEN:
                if token in lower:
                    found.append(f"{path}.{key}")
            found.extend(_walk_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_forbidden(child, f"{path}[{index}]"))
    return found


def _find(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise RuntimeError(f"{name} not found in combined artifact")
    return matches[0]


def _analyse_artifact(artifact: dict[str, Any], work: Path) -> dict[str, Any]:
    archive = _request(artifact["archive_download_url"])
    zip_path = work / "combined.zip"
    zip_path.write_bytes(archive)
    extracted = work / "combined"
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extractall(extracted)

    summary_path = _find(extracted, "summary.json")
    candidates_path = _find(extracted, "recognition_candidates.json")
    csv_path = _find(extracted, "recognition_candidates.csv")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    candidates_payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    forbidden_paths = _walk_forbidden(summary) + _walk_forbidden(candidates_payload)
    csv_text = csv_path.read_text(encoding="utf-8")
    forbidden_csv = [token for token in FORBIDDEN if token in csv_text.lower()]
    if forbidden_paths or forbidden_csv:
        raise RuntimeError(f"forbidden outcome fields: paths={forbidden_paths[:10]} csv={forbidden_csv}")

    rows = list(csv.DictReader(io.StringIO(csv_text)))
    by_symbol = Counter(row.get("symbol", "") for row in rows)
    by_side = Counter(row.get("side", "") for row in rows)
    by_state = Counter(row.get("setup_state", "") for row in rows)
    by_entry = Counter(row.get("entry_ready", "") for row in rows)

    review_dir = work / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(summary_path, review_dir / "summary.json")
    shutil.copy2(candidates_path, review_dir / "recognition_candidates.json")
    shutil.copy2(csv_path, review_dir / "recognition_review_queue.csv")

    return {
        "summary": summary,
        "candidate_rows": len(rows),
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_side": dict(sorted(by_side.items())),
        "by_state": dict(by_state.most_common()),
        "by_entry_ready": dict(sorted(by_entry.items())),
        "no_pnl_contract": "PASS",
        "review_dir": str(review_dir),
    }


def _render(report: dict[str, Any]) -> str:
    run = report.get("run") or {}
    lines = [MARKER, "## SMOKE MTF V2 — frozen real-recognition status", ""]
    if not run:
        lines += [f"- Target SHA: `{report['target_sha']}`", "- Status: **RUN_NOT_FOUND**"]
        return "\n".join(lines)
    lines += [
        f"- Target SHA: `{report['target_sha']}`",
        f"- Run: [{run['id']}]({run['html_url']})",
        f"- Status: **{run['status']} / {run.get('conclusion') or 'pending'}**",
    ]
    jobs = report.get("jobs") or []
    failed = [job for job in jobs if job.get("conclusion") not in (None, "success", "skipped")]
    if failed:
        lines += ["", "### Failed jobs"]
        for job in failed:
            lines.append(f"- `{job['name']}` — **{job.get('conclusion')}**")
    recognition = report.get("recognition")
    if recognition:
        summary = recognition["summary"]
        lines += [
            "",
            "### Combined artifact",
            f"- Evaluated 15m bars: **{summary.get('evaluated_15m_bars', 0)}**",
            f"- Side snapshots: **{summary.get('evaluated_side_snapshots', 0)}**",
            f"- Qualifying snapshots: **{summary.get('qualifying_snapshots', 0)}**",
            f"- Selected review snapshots: **{summary.get('selected_snapshots', recognition['candidate_rows'])}**",
            f"- No-PnL/future-outcome contract: **{recognition['no_pnl_contract']}**",
            f"- By side: `{json.dumps(recognition['by_side'], ensure_ascii=False)}`",
            f"- By state: `{json.dumps(recognition['by_state'], ensure_ascii=False)}`",
        ]
        reasons = list((summary.get("reason_counts") or {}).items())[:10]
        if reasons:
            lines += ["", "### Top blocking reasons"]
            lines.extend(f"- `{name}`: **{count}**" for name, count in reasons)
    lines += ["", "PnL, TP/SL outcomes, MFE/MAE and future returns were not used."]
    return "\n".join(lines)


def _upsert_comment(repo: str, pr_number: int, body: str) -> None:
    comments = _request(f"/repos/{repo}/issues/{pr_number}/comments?per_page=100")
    existing = next((item for item in comments if MARKER in str(item.get("body", ""))), None)
    if existing:
        _request(f"/repos/{repo}/issues/comments/{existing['id']}", "PATCH", {"body": body})
    else:
        _request(f"/repos/{repo}/issues/{pr_number}/comments", "POST", {"body": body})


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    target_sha = os.environ["TARGET_SHA"].strip()
    workflow_name = os.environ.get("WORKFLOW_NAME", "SMOKE MTF V2 Real Recognition V1")
    pr_number = int(os.environ.get("PR_NUMBER", "2"))
    out = Path(os.environ.get("OUT_DIR", "results/smoke_mtf_v2_status_probe"))
    out.mkdir(parents=True, exist_ok=True)

    query = urllib.parse.urlencode({"head_sha": target_sha, "per_page": 100})
    payload = _request(f"/repos/{repo}/actions/runs?{query}")
    runs = [
        run for run in payload.get("workflow_runs", [])
        if run.get("name") == workflow_name and run.get("head_sha") == target_sha
    ]
    report: dict[str, Any] = {"target_sha": target_sha, "workflow_name": workflow_name}
    if runs:
        run = max(runs, key=lambda item: int(item["id"]))
        report["run"] = {
            key: run.get(key)
            for key in ("id", "name", "status", "conclusion", "html_url", "head_sha", "run_number", "created_at", "updated_at")
        }
        jobs_payload = _request(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
        report["jobs"] = [
            {key: job.get(key) for key in ("id", "name", "status", "conclusion", "html_url", "started_at", "completed_at")}
            for job in jobs_payload.get("jobs", [])
        ]
        artifacts_payload = _request(f"/repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
        artifacts = artifacts_payload.get("artifacts", [])
        report["artifacts"] = [
            {key: artifact.get(key) for key in ("id", "name", "size_in_bytes", "expired", "archive_download_url")}
            for artifact in artifacts
        ]
        combined = next(
            (artifact for artifact in artifacts if artifact.get("name") == "smoke-mtf-v2-real-recognition-v1-combined" and not artifact.get("expired")),
            None,
        )
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            if combined is None:
                report["artifact_error"] = "successful run has no combined artifact"
            else:
                report["recognition"] = _analyse_artifact(combined, out)

    (out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    body = _render(report)
    (out / "pr_comment.md").write_text(body + "\n", encoding="utf-8")
    _upsert_comment(repo, pr_number, body)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
