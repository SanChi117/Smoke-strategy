#!/usr/bin/env python3
"""Aggregate exactly 100 outcome-blind FTA-first V3 recognition partitions."""
from __future__ import annotations
import argparse, json, re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

FORBIDDEN=("pnl","future_return","trade_outcome","tp_result","sl_result","mfe","mae","win_rate","profit_factor","net_return","drawdown","exit_time","exit_price","exit_reason","gross_return","funding_return")
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","AAVEUSDT")
SIDES=("long","short")

def assert_blind(v: Any, path: str = "$") -> None:
    if isinstance(v, Mapping):
        for k,c in v.items():
            n=re.sub(r"[^a-z0-9]+","_",str(k).lower()).strip("_")
            for f in FORBIDDEN:
                if f in n: raise AssertionError(f"forbidden field {path}.{k}: {f}")
            assert_blind(c,f"{path}.{k}")
    elif isinstance(v,list):
        for i,c in enumerate(v): assert_blind(c,f"{path}[{i}]")

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--input-dir",required=True); ap.add_argument("--out",required=True); a=ap.parse_args()
    rows=[]
    for p in sorted(Path(a.input_dir).rglob("*.json")):
        x=json.loads(p.read_text());
        if x.get("study_id")=="SMOKE_MTF_FTA_FIRST_V3_RECOGNITION_V1" and x.get("partition_key"): rows.append(x)
    keys=[r["partition_key"] for r in rows]
    if len(rows)!=100 or len(set(keys))!=100: raise AssertionError(f"expected 100 unique partitions, got {len(rows)}/{len(set(keys))}")
    expected={f"{f}:{s}:{d}" for f in range(10) for s in SYMBOLS for d in SIDES}
    if set(keys)!=expected: raise AssertionError(f"partition mismatch missing={sorted(expected-set(keys))[:5]} extra={sorted(set(keys)-expected)[:5]}")
    state=Counter(); reasons=Counter(); routes=Counter(); targets=Counter(); stops=Counter(); fingerprints={}; evaluated=allowed=duplicates=0
    per_fold={str(i):{"evaluated_15m_snapshots":0,"independent_entry_ready_count":0} for i in range(10)}
    for r in rows:
        assert_blind(r); evaluated+=r["evaluated_15m_snapshots"]; allowed+=r["allowed_snapshots"]; duplicates+=r["duplicate_allowed_snapshots"]
        state.update(r["state_counts"]); reasons.update(r["reason_counts"]); routes.update(r["route_counts"]); targets.update(r["target_timeframe_counts"]); stops.update(r["stop_source_counts"])
        fold=str(r["fold"]); per_fold[fold]["evaluated_15m_snapshots"]+=r["evaluated_15m_snapshots"]
        for rec in r["independent_entry_ready"]:
            fp=rec.get("independent_fingerprint")
            if not fp: raise AssertionError("entry-ready record missing fingerprint")
            fingerprints.setdefault(fp,rec)
    for rec in fingerprints.values(): per_fold[str(rec["fold"])]["independent_entry_ready_count"]+=1
    payload={
      "study_id":"SMOKE_MTF_FTA_FIRST_V3_RECOGNITION_V1","mode":"OUTCOME_BLIND_PARTITIONED_RECOGNITION",
      "candidate_id":"SMOKE_MTF_FTA_FIRST_V3_FROZEN_CANDIDATE_1","partition_count":100,"symbols":list(SYMBOLS),"sides":list(SIDES),"folds":10,
      "recognition_start":"2025-01-01","recognition_end_exclusive":"2026-07-01","evaluated_15m_snapshots":evaluated,
      "state_counts":dict(state),"reason_counts":dict(reasons.most_common()),"route_counts":dict(routes),"target_timeframe_counts":dict(targets),"stop_source_counts":dict(stops),
      "allowed_snapshots":allowed,"independent_entry_ready_count":len(fingerprints),"duplicate_allowed_snapshots":allowed-len(fingerprints),
      "independent_entry_ready":list(fingerprints.values()),"per_fold":per_fold,
      "decision":"READY_FOR_SEMANTIC_REPLAY" if len(fingerprints)>=60 else "CLOSE_BELOW_60_ENTRY_READY",
      "contract":{"closed_candles_only":True,"future_outcomes_excluded":True,"profitability_metrics_excluded":True,"minimum_independent_cases_before_profitability":60}
    }
    assert_blind(payload)
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:payload[k] for k in ("partition_count","evaluated_15m_snapshots","independent_entry_ready_count","decision")},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
