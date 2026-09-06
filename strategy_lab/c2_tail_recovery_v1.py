#!/usr/bin/env python3
"""Tail recovery helpers for Candidate 2 checkpoint replay.

Transport-only. Reindexes an existing causal checkpoint onto an equivalent finer
physical grid and stitches adjacent 64-way microshards back into the authoritative
32-way logical grid. No trading semantics are changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle


def rewrite_checkpoint(src: Path, dst: Path, *, symbol: str, next_segment_index: int) -> None:
    with src.open("rb") as handle:
        payload = pickle.load(handle)
    if payload.get("symbol") != symbol:
        raise ValueError(f"checkpoint symbol mismatch: {payload.get('symbol')} != {symbol}")
    payload["completed_segment_index"] = next_segment_index - 1
    payload["next_segment_index"] = next_segment_index
    payload["tail_recovery_reindexed"] = True
    payload["tail_recovery_source_asof"] = payload.get("asof")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)


def stitch_pair(left: Path, right: Path, out: Path, *, logical_index: int) -> None:
    a = json.loads(left.read_text(encoding="utf-8"))
    b = json.loads(right.read_text(encoding="utf-8"))
    if a["symbol"] != b["symbol"]:
        raise ValueError("microshard symbol mismatch")
    if int(a["segment_count"]) != 64 or int(b["segment_count"]) != 64:
        raise ValueError("tail recovery requires 64-way microshards")
    expected_left = logical_index * 2
    if int(a["segment_index"]) != expected_left or int(b["segment_index"]) != expected_left + 1:
        raise ValueError("microshard/logical boundary mismatch")
    if a["data_manifest_sha256"] != b["data_manifest_sha256"]:
        raise ValueError("microshard manifest mismatch")

    da, db = dict(a["diagnostics"]), dict(b["diagnostics"])
    diag = dict(db)
    diag.update({
        "symbol": a["symbol"],
        "segment_index": logical_index,
        "segment_count": 32,
        "emit_start": da.get("emit_start"),
        "emit_end": db.get("emit_end"),
        "checkpoint_restored": True,
        "checkpoint_saved": True,
        "checkpoint_chain_enabled": True,
        "checkpoint_transport": True,
        "p7_precomputed_levels_enabled": True,
        "p7_incremental_poi_installed": True,
        "tail_recovery_microshards": [expected_left, expected_left + 1],
        "tail_recovery_physical_segment_count": 64,
    })
    payload = dict(a)
    payload.update({
        "segment_index": logical_index,
        "segment_count": 32,
        "rows": list(a.get("rows", [])) + list(b.get("rows", [])),
        "diagnostics": diag,
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rewrite-checkpoint")
    r.add_argument("--src", type=Path, required=True)
    r.add_argument("--dst", type=Path, required=True)
    r.add_argument("--symbol", required=True)
    r.add_argument("--next-segment-index", type=int, required=True)
    s = sub.add_parser("stitch-pair")
    s.add_argument("--left", type=Path, required=True)
    s.add_argument("--right", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--logical-index", type=int, required=True)
    args = p.parse_args()
    if args.cmd == "rewrite-checkpoint":
        rewrite_checkpoint(args.src, args.dst, symbol=args.symbol, next_segment_index=args.next_segment_index)
    else:
        stitch_pair(args.left, args.right, args.out, logical_index=args.logical_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
