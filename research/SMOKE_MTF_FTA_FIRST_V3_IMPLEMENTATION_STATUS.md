# SMOKE MTF FTA-FIRST V3 — Implementation Status

Status: `CORRECTED_OUTCOME_BLIND_RECOGNITION_RUNNING`

Branch: `agent/smoke-mtf-fta-first-v3`

Draft PR: `#3`

## Completed

- Separate V3 branch created from the frozen V2 research infrastructure.
- One candidate preregistered before implementation.
- External 4H/1D/1W/1M FTA is selected before route acceptance.
- Active HTF POI is required.
- Allowed routes remain fresh H1 raid or H1 VC plus later closed 15m test.
- Causal 5m BOS is required after route confirmation.
- A later closed 15m pullback to the broken BOS pivot is required.
- Entry is the next aligned 15m open.
- Stop priority is post-BOS 5m swing, post-BOS 15m swing, then pullback wick.
- The preselected external FTA is never moved to manufacture RR.
- RR 1.70 and quality 55 remain fixed.
- Entry-core, no-PnL JSON export, aggregation/global-dedup and reused V2 causal regression tests pass.
- SOLUSDT one-day benchmark completed successfully.
- Benchmark maximum runtime was 67.3 seconds per side and authorised partitioned recognition.
- The first auto-generated recognition run was cancelled and invalidated before acceptance because its chronological fold dates were wrong.
- Correct contiguous fold boundaries were generated from 546 days using six 55-day folds followed by four 54-day folds.
- Corrected recognition run `30079138170` was started from trigger SHA `d267de93d8f42b385f3f9dea7a9501e4d588bda3`.

## Current run contract

- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, AAVEUSDT.
- Directions: LONG and SHORT.
- Recognition period: 2025-01-01 through 2026-07-01 exclusive.
- Ten contiguous chronological folds.
- Exactly 100 outcome-blind partitions.
- Global independent-fingerprint deduplication.
- Minimum 60 independent ENTRY_READY before semantic replay and freeze.

## Not yet completed

- Corrected 100-part recognition aggregate.
- Independent ENTRY_READY count.
- Exact semantic replay and causal-vs-fast runtime equivalence.
- Recognition freeze.

Profitability, holdout, VPS, paper and live remain prohibited.
