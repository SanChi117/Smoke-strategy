#!/usr/bin/env python3
"""Read one frozen SMOKE MTF V2 export benchmark from GitHub Actions."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

MARKER = "<!-- smoke-mtf-v2-export-diagnostic-status -->"
FORBIDDEN = ("pnl", "future_return", "realized_return", "tp_hit", "sl_hit", "mfe", "mae")


def request(path_or_url: str, method: str = "GET", payload: Any | None = None) -> Any:
    url = path_or_url if path_or_url.startswith("http") else f"https://api.github.com{path_or_url}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
        if "application/json" in response.headers.get("Content-Type", ""):
            return json.loads(raw.decode("utf-8"))
        return raw


def find(root: Path, name: str) -> Path | None:
    matches = list(root.rglob(name))
    return matches[0] if matches else None


def parse_elapsed(text: str) -> tuple[str | None, float | None]:
    match = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*([^\r\n]+)", text)
    if not match:
        return None, None
    raw = match.group(1).strip()
    parts = raw.split(":")
    try:
        if len(parts) == 3:
            seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            seconds = float(parts[0]) * 60 + float(parts[1])
        else:
            seconds = float(parts[0])
    except ValueError:
        return raw, None
    return raw, seconds


def parse_log(text: str) -> dict[str, Any]:
    elapsed_raw, elapsed_seconds = parse_elapsed(text)
    rss = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", text)
    status = re.search(r"Exit status:\s*(\d+)", text)
    return {
        "elapsed_raw": elapsed_raw,
        "elapsed_seconds": elapsed_seconds,
        "max_rss_kb": int(rss.group(1)) if rss else None,
        "process_exit_status": int(status.group(1)) if status else None,
    }


def assert_no_outcomes(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in FORBIDDEN):
                raise RuntimeError(f"forbidden outcome field at {path}.{key}")
            assert_no_outcomes(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_outcomes(child, f"{path}[{index}]")


def analyse_artifact(artifact: dict[str, Any], out: Path) -> dict[str, Any]:
    archive = request(artifact["archive_download_url"])
    zip_path = out / "diagnostic.zip"
    zip_path.write_bytes(archive)
    extracted = out / "diagnostic"
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extractall(extracted)
    log_path = find(extracted, "export-diagnostic.log")
    summary_path = find(extracted, "summary.json")
    result: dict[str, Any] = {}
    if log_path:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        result["performance"] = parse_log(text)
        result["log_tail"] = "\n".join(text.splitlines()[-80:])
    if summary_path:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert_no_outcomes(summary)
        result["summary"] = summary
        result["no_pnl_contract"] = "PASS"
    else:
        result["summary_missing"] = True
    return result


def render(report: dict[str, Any]) -> str:
    run = report.get("run") or {}
    lines = [MARKER, "## SMOKE MTF V2 — cached export benchmark", ""]
    lines.append(f"- Target SHA: `{report['target_sha']}`")
    if not run:
        lines.append("- Status: **RUN_NOT_FOUND**")
        return "\n".join(lines)
    lines += [
        f"- Run: [{run['id']}]({run['html_url']})",
        f"- Status: **{run['status']} / {run.get('conclusion') or 'pending'}**",
    ]
    diagnostic = report.get("diagnostic") or {}
    perf = diagnostic.get("performance") or {}
    summary = diagnostic.get("summary") or {}
    if perf:
        lines += [
            f"- Wall time: **{perf.get('elapsed_raw')}**",
            f"- Peak RSS: **{perf.get('max_rss_kb')} kB**",
            f"- Process exit: **{perf.get('process_exit_status')}**",
        ]
        seconds = perf.get("elapsed_seconds")
        if seconds is not None:
            projected = seconds * 7 / 60
            lines.append(f"- Linear 7-day projection: **{projected:.2f} min**")
    if summary:
        lines += [
            f"- Evaluated 15m bars: **{summary.get('evaluated_15m_bars', 0)}**",
            f"- Side snapshots: **{summary.get('evaluated_side_snapshots', 0)}**",
            f"- Selected snapshots: **{summary.get('selected_snapshots', 0)}**",
            f"- No-PnL contract: **{diagnostic.get('no_pnl_contract')}**",
            f"- Execution cache: `{json.dumps(summary.get('execution_cache', {}), ensure_ascii=False)}`",
        ]
    lines += ["", "Trading rules, thresholds, periods and sampling were not changed."]
    return "\n".join(lines)


def upsert_comment(repo: str, pr: int, body: str) -> None:
    comments = request(f"/repos/{repo}/issues/{pr}/comments?per_page=100")
    existing = next((item for item in comments if MARKER in str(item.get("body", ""))), None)
    if existing:
        request(f"/repos/{repo}/issues/comments/{existing['id']}", "PATCH", {"body": body})
    else:
        request(f"/repos/{repo}/issues/{pr}/comments", "POST", {"body": body})


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    target_sha = os.environ["TARGET_SHA"].strip()
    workflow_name = "SMOKE MTF V2 Export Diagnostic"
    out = Path(os.environ.get("OUT_DIR", "results/smoke_mtf_v2_export_probe"))
    out.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode({"head_sha": target_sha, "per_page": 100})
    payload = request(f"/repos/{repo}/actions/runs?{query}")
    runs = [run for run in payload.get("workflow_runs", []) if run.get("name") == workflow_name]
    report: dict[str, Any] = {"target_sha": target_sha, "workflow_name": workflow_name}
    if runs:
        run = max(runs, key=lambda item: int(item["id"]))
        report["run"] = {key: run.get(key) for key in ("id", "status", "conclusion", "html_url", "head_sha", "created_at", "updated_at")}
        jobs = request(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
        report["jobs"] = [{key: job.get(key) for key in ("id", "name", "status", "conclusion", "started_at", "completed_at")} for job in jobs.get("jobs", [])]
        artifacts = request(f"/repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
        artifact = next((item for item in artifacts if item.get("name") == "smoke-mtf-v2-export-diagnostic" and not item.get("expired")), None)
        if artifact:
            report["diagnostic"] = analyse_artifact(artifact, out)
    body = render(report)
    (out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "pr_comment.md").write_text(body + "\n", encoding="utf-8")
    try:
        upsert_comment(repo, 2, body)
    except Exception as exc:
        print(f"::warning::Comment not published: {type(exc).__name__}: {exc}")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
