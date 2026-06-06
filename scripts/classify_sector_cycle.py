#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except Exception:
        return d


def i(v, d=0):
    try:
        return int(float(v)) if v not in (None, "") else d
    except Exception:
        return d


def read_rows(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def bucket(row):
    pf = f(row.get("wfo_avg_pf"))
    ret = f(row.get("wfo_avg_ret_pct"))
    dd = f(row.get("wfo_worst_dd_pct"), 999.0)
    trades = i(row.get("wfo_executed"))
    pos = f(row.get("wfo_positive_fold_pct"))
    valid = i(row.get("wfo_valid_folds"))
    decision = row.get("decision", "")
    best = row.get("best_config", "")

    if decision == "ERROR" or not best or valid <= 0 or trades <= 0:
        return "BLOCK", "no valid sector result"
    if pos >= 100 and pf >= 1.6 and ret > 0 and dd <= 8 and trades >= 30:
        return "STRONG", "PF>=1.6, positive folds 4/4, DD<=8, trades>=30"
    if pos >= 75 and pf >= 1.2 and ret > 0 and dd <= 12 and trades >= 10:
        return "WATCH", "positive but needs deeper research"
    if pf > 1 and ret > 0 and trades > 0:
        return "WATCH", "weak positive edge"
    return "BLOCK", "weak PF, bad return, high DD or too few trades"


def sort_key(row):
    rank = {"STRONG": 2, "WATCH": 1, "BLOCK": 0}.get(row.get("bucket"), 0)
    return (rank, f(row.get("wfo_avg_pf")), f(row.get("wfo_avg_ret_pct")), -f(row.get("wfo_worst_dd_pct"), 999.0), i(row.get("wfo_executed")))


def write_md(path: Path, rows, baseline):
    ranked = sorted(rows, key=sort_key, reverse=True)
    lines = ["# Sector Classification", "", "Research report. Not a production approval.", ""]
    for name in ["STRONG", "WATCH", "BLOCK"]:
        lines += [f"## {name} sectors", ""]
        part = [r for r in ranked if r.get("bucket") == name]
        if not part:
            lines += ["- none", ""]
            continue
        for r in part:
            lines.append(
                f"- **{r.get('label')}**: best={r.get('best_config')}, decision={r.get('decision')}, "
                f"wfo_pf={r.get('wfo_avg_pf')}, wfo_ret={r.get('wfo_avg_ret_pct')}%, "
                f"dd={r.get('wfo_worst_dd_pct')}%, trades={r.get('wfo_executed')}, "
                f"positive={r.get('wfo_positive_fold_pct')}%, reason={r.get('bucket_reason')}"
            )
        lines.append("")
    lines += [
        "## Baseline candidate", "",
        f"- name: `{baseline['name']}`",
        f"- active sectors: {', '.join(baseline['active_sectors']) or 'none'}",
        f"- watch sectors: {', '.join(baseline['watch_sectors']) or 'none'}",
        "- next: deeper sector research, then paper validation",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="results/sector_research_cycle/sector_cycle_summary.csv")
    p.add_argument("--out-dir", default="results/sector_research_cycle")
    p.add_argument("--max-active-sectors", type=int, default=3)
    args = p.parse_args()

    out = Path(args.out_dir)
    rows = read_rows(Path(args.input))
    if not rows:
        raise SystemExit(f"No rows in {args.input}")

    classified = []
    for row in rows:
        b, reason = bucket(row)
        classified.append({**row, "bucket": b, "bucket_reason": reason})
    ranked = sorted(classified, key=sort_key, reverse=True)

    strong = [r for r in ranked if r.get("bucket") == "STRONG" and r.get("label") != "combined_all_sectors"]
    watch = [r for r in ranked if r.get("bucket") == "WATCH" and r.get("label") != "combined_all_sectors"]
    baseline = {
        "name": "SECTOR_ROTATION_DYNAMIC_MICRO_STRICT",
        "status": "research_candidate",
        "active_sectors": [r.get("label") for r in strong[: args.max_active_sectors]],
        "watch_sectors": [r.get("label") for r in watch[: args.max_active_sectors]],
        "ranked_rows": ranked,
    }

    write_rows(out / "sector_classification.csv", ranked)
    write_md(out / "sector_classification.md", ranked, baseline)
    (out / "sector_rotation_baseline_candidate.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out / "sector_classification.md")
    print(out / "sector_rotation_baseline_candidate.json")


if __name__ == "__main__":
    main()
