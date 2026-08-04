# SMOKE CORE 1.0 — P7 Full Partitioned Recognition Preregistration V1

## Frozen candidate

- Candidate: `SMOKE_CORE_1_0_CANDIDATE_1`.
- Frozen upstream base: P6 head `cfb9b433449f5f5aa8902f41d6b622a2d8ed5847`.
- Pilot PASS head: `b185bd9b7d0ef69d450b07b895627f386fed8380`.
- No P1-P7 threshold, family weight, lifecycle, provenance, fingerprint/rearm rule, economics/risk rule or recognition gate may be changed after this file is committed.

## Recognition ID

`SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1`

## Fixed universe

- `BTCUSDT`
- `ETHUSDT`
- `SOLUSDT`
- `LINKUSDT`
- `AAVEUSDT`
- both `LONG` and `SHORT`

## Fixed historical interval

- Start inclusive: `2024-01-01T00:00:00+00:00`.
- End inclusive: `2024-06-30T23:55:00+00:00`.
- Base candle interval: Binance USD-M Futures `5m` closed klines.
- The interval is fixed before any full-recognition count is produced.

## Fixed acquisition source

Public immutable monthly Binance Vision archives:

`https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM}.zip`

Exactly 30 archives are required: five symbols times six months (`2024-01` through `2024-06`). Acquisition must fail closed if any archive is missing, unreadable, has an unexpected filename, duplicate/open timestamp, non-5m cadence inside a continuous segment, malformed OHLCV row, timestamp outside the fixed interval, or symbol mismatch.

The acquisition job must write a manifest containing URL, archive filename, byte size, SHA-256, row count, first open time and last open time for every archive. The canonical combined candle files and manifest are artifacts of the same workflow run. No fallback exchange, API, timeframe or date extension is allowed.

## Causal execution

- Closed candles only.
- No future candle may be read beyond each evaluation timestamp.
- P1-P6 default frozen configurations are identical for every symbol and fold.
- Recognition consumes only P6 scenario decisions transformed into the frozen P7 `RecognitionObservation` schema.
- No outcome, target-hit, stop-hit, return, MFE, MAE, PnL, equity or drawdown field may be read or serialized.

## Fixed evaluation schedule

- Evaluate on every fully closed `15m` boundary derived from the canonical `5m` series.
- Warm-up data inside the fixed interval may be used causally but observations before sufficient P1-P6 dependencies exist are excluded with exact block reasons.
- No retrospective entry emission is permitted.

## Exact folds

The full interval is split into exactly 10 contiguous chronological folds by timestamp index after canonical 15m boundary construction. Fold boundaries are deterministic equal-count partitions; earlier folds receive one extra boundary when the count is not divisible by 10. A boundary timestamp belongs to exactly one fold.

Global fingerprint de-duplication is applied after concatenating all folds. The same fingerprint crossing a fold boundary counts once. A repeated fingerprint counts again only through the frozen explicit rearm lineage contract.

## Counted observations

Count only independent observations satisfying all of:

- symbol in the fixed universe;
- direction `LONG` or `SHORT`;
- lifecycle `ENTRY_READY`;
- decision `VALID_SETUP` or `HIGH_CONFIDENCE_SETUP`;
- economics valid;
- risk valid;
- no hard block;
- complete reconstructible POI, liquidity, interaction, anchor, structure, evidence and evidence-cluster provenance.

## Recognition gate

- PASS: at least 60 independent counted observations.
- FAIL: fewer than 60.

A FAIL closes Candidate 1 at recognition. No automatic loosening, threshold change, second period, second source or second recognition attempt is allowed. Profitability and P8 are forbidden after recognition FAIL.

## Frozen outputs

Allowed outputs are limited to acquisition manifest, causal diagnostics, block reasons, lifecycle counts, duplicate/rearm diagnostics, provenance diagnostics, counts by symbol/direction/fold/family and the final recognition gate. No market outcome fields are allowed.
