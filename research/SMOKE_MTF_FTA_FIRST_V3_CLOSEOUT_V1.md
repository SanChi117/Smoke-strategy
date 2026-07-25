# SMOKE MTF FTA-FIRST V3 — Recognition Closeout V1

Status: `CLOSED_WITHOUT_PROFITABILITY_TEST`

## Authoritative recognition run

- Workflow: `SMOKE MTF FTA-First V3 Partitioned Recognition`
- Run ID: `30079138170`
- Trigger SHA: `d267de93d8f42b385f3f9dea7a9501e4d588bda3`
- Artifact: `smoke-mtf-fta-first-v3-partitioned-recognition-result`
- Artifact digest: `sha256:acfc3caa267d7f75ff01beb077853fb356c0c7925cb178c529c20d8463ea03da`
- Invalidated run `30078535250` / SHA `4e235ef4e25706219742cd361489b4db986858fd` is excluded permanently because its fold boundaries were wrong.

## Frozen recognition contract

- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, AAVEUSDT
- Sides: LONG and SHORT
- Period: 2025-01-01 through 2026-06-30; end exclusive 2026-07-01
- Ten contiguous chronological folds with the preregistered corrected boundaries
- 100 unique outcome-blind partitions
- No PnL, future return, trade outcome, TP/SL result, MFE, MAE, PF, net return or drawdown
- No threshold tuning

## Result

- Evaluated 15m snapshots: 524,160
- Independent ENTRY_READY structures: 48
- Required before profitability: 60
- Recognition gate: FAIL
- Decision: `CLOSE_V3_WITHOUT_PROFITABILITY_TEST`

Per symbol independent ENTRY_READY:

- BTCUSDT: 10
- ETHUSDT: 12
- SOLUSDT: 7
- LINKUSDT: 9
- AAVEUSDT: 10

Per fold independent ENTRY_READY:

- Fold 0: 5
- Fold 1: 8
- Fold 2: 3
- Fold 3: 2
- Fold 4: 3
- Fold 5: 1
- Fold 6: 1
- Fold 7: 6
- Fold 8: 2
- Fold 9: 17

## Outcome-blind funnel state totals

- WAIT_H1_ROUTE: 425,442
- WAIT_5M_BOS: 57,924
- WAIT_NEXT_15M_OPEN: 18,489
- WAIT_15M_PULLBACK: 13,391
- RR_BLOCKED: 5,816
- WAIT_HTF_POI: 2,127
- WAIT_POST_BOS_STOP: 346
- NO_CONTEXT: 306
- WAIT_EXTERNAL_FTA: 271
- ENTRY_READY: 48

Routes:

- fresh H1 raid: 78,118
- H1 VC with later 15m test: 17,896

External FTA timeframes:

- 4H: 458,480
- 1D: 57,186
- 1W: 5,875
- 1M: 920

Stop sources:

- 15m pullback-wick fallback: 5,556
- 5m post-BOS protected swing: 654

## Governance decision

The preregistered minimum of 60 independent ENTRY_READY structures was not reached. V3 is closed without semantic freeze and without profitability testing. No development profitability, holdout, VPS, paper or live stage is permitted for this candidate. The candidate must not be loosened or tuned from these results.
