#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from strategy_lab.outcome_blind_recognition_v1 import ALLOWED_SYMBOLS, RecognitionObservation, dedupe_global, is_counted, report_to_no_outcome_dict, run_full_recognition
from strategy_lab.p7_full_recognition_runner_v1 import DATA_ROOT, RECOGNITION_ID, REPORT_PATH, ScenarioFamily, _assert_no_outcomes, _jsonable, load_locked_dataset, scan_symbol

PART_ROOT = Path('research_outputs/p7_full_recognition_parts_v1')
TUPLES = ('liquidity_ids','interaction_ids','evidence_ids','evidence_cluster_ids','block_reasons','hard_blocks')

def run_symbol(symbol: str) -> None:
    manifest, candles = load_locked_dataset(DATA_ROOT)
    rows, diagnostics = scan_symbol(symbol, candles[symbol])
    payload = {'recognition_id': RECOGNITION_ID, 'symbol': symbol, 'manifest_sha': hashlib.sha256((DATA_ROOT/'p7_full_recognition_data_manifest_v1.json').read_bytes()).hexdigest(), 'rows': [], 'diagnostics': diagnostics}
    for row in rows:
        item = asdict(row); item['timestamp'] = row.timestamp.isoformat(); payload['rows'].append(item)
    _assert_no_outcomes(payload)
    PART_ROOT.mkdir(parents=True, exist_ok=True)
    (PART_ROOT/f'{symbol}.json').write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')

def aggregate() -> dict:
    manifest, _ = load_locked_dataset(DATA_ROOT)
    manifest_sha = hashlib.sha256((DATA_ROOT/'p7_full_recognition_data_manifest_v1.json').read_bytes()).hexdigest()
    rows, diagnostics = [], []
    for symbol in ALLOWED_SYMBOLS:
        payload = json.loads((PART_ROOT/f'{symbol}.json').read_text(encoding='utf-8'))
        if payload['recognition_id'] != RECOGNITION_ID or payload['symbol'] != symbol or payload['manifest_sha'] != manifest_sha: raise ValueError('partition contract mismatch')
        _assert_no_outcomes(payload); diagnostics.append(payload['diagnostics'])
        for item in payload['rows']:
            item['timestamp'] = datetime.fromisoformat(item['timestamp'])
            for key in TUPLES: item[key] = tuple(item[key])
            rows.append(RecognitionObservation(**item))
    report = run_full_recognition(rows)
    deduped, _ = dedupe_global(rows); counted = tuple(row for row in deduped if is_counted(row))
    result = {'recognition_id': RECOGNITION_ID, 'candidate_id': 'SMOKE_CORE_1_0_CANDIDATE_1', 'data_manifest_sha256': manifest_sha, 'source': manifest['source'], 'interval': manifest['interval'], 'start_inclusive': manifest['start_inclusive'], 'end_inclusive': manifest['end_inclusive'], 'fold_count': 10, 'status': 'PASS' if report.gate_pass else 'FAIL', 'recognition': report_to_no_outcome_dict(report), 'by_family': {family.value: sum(row.family == family.value for row in counted) for family in ScenarioFamily}, 'diagnostics': diagnostics}
    _assert_no_outcomes(result); REPORT_PATH.parent.mkdir(parents=True, exist_ok=True); REPORT_PATH.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding='utf-8'); return result

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--symbol', choices=ALLOWED_SYMBOLS); parser.add_argument('--aggregate', action='store_true'); args=parser.parse_args()
    if args.symbol: run_symbol(args.symbol)
    elif args.aggregate: print(json.dumps(aggregate()['recognition'], sort_keys=True))
    else: parser.error('choose --symbol or --aggregate')
    return 0
if __name__ == '__main__': raise SystemExit(main())
