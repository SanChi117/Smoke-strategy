# SMOKE CORE 1.0 — P7 Outcome-Blind Pilot and Recognition Preregistration V1

## Scope

P7 measures recognition behavior only. It must not read, calculate, serialize, optimize against, or expose PnL, returns, MFE, MAE, TP/SL outcomes, profit factor, drawdown, equity, exit reason, or future candles beyond each evaluation timestamp.

## Frozen upstream candidate

- Candidate: `SMOKE_CORE_1_0_CANDIDATE_1`
- P6 base head: `cfb9b433449f5f5aa8902f41d6b622a2d8ed5847`
- All P1-P6 contracts, defaults, family weights, lifecycle transitions, evidence provenance, economics/risk gates, fingerprints and rearm rules are frozen.
- P7 may repair only technical defects or semantic defects directly demonstrated against an existing contract, with a regression test. Recognition counts may never be used to relax or tighten a rule.

## Phase A — fixed outcome-blind pilot

The pilot uses a small, fixed chronological subset selected before any recognition report is read. It validates only:

- causal closed-candle execution;
- block-rate accounting by exact reason;
- evidence provenance and cluster de-duplication;
- scenario fingerprint uniqueness;
- duplicate suppression and rearm behavior;
- lifecycle transition consistency;
- no retroactive ENTRY_READY emission;
- no forbidden outcome fields;
- operational strictness diagnostics without market outcomes.

### Frozen pilot fixture

- Pilot ID: `SMOKE_CORE_P7_PILOT_FIXED_V1`.
- Source file: `strategy_lab/outcome_blind_pilot_v1.py`.
- Chronological evaluation interval: `2026-01-05T00:00:00+00:00` through `2026-01-06T09:00:00+00:00`.
- Exactly 12 deterministic causal P6 observations are constructed before execution.
- The fixture spans all three frozen scenario families, all five recognition symbols, both directions, ENTRY_READY and non-entry lifecycle states, economics/risk cancellations, expiry and causal invalidation.
- Every case has a unique frozen P6 fingerprint and complete POI/liquidity/interaction/anchor/structure evidence provenance.
- Hard blocks are limited to preregistered prefixes `causal:`, `data:`, `economics:` and `risk:`.
- The fixture contains no price outcomes, future returns, target/stop results, PnL, MFE, MAE, drawdown or equity fields.
- Pilot counts are diagnostics only and cannot change any threshold, weight, lifecycle, provenance, fingerprint or rearm rule.

Pilot PASS requires:

1. zero future/outcome-field access;
2. zero duplicate independent fingerprints after global de-duplication;
3. zero invalid lifecycle transitions;
4. exact reproducibility on a second replay;
5. every hard block mapped to a preregistered causal/data/economics/risk reason;
6. no unexplained missing provenance links;
7. no code or threshold changes based on event counts.

No minimum number of setups is required in the pilot. Pilot event counts are diagnostic only.

## Phase B — full partitioned recognition

Allowed only after Phase A PASS.

### Universe

- BTCUSDT
- ETHUSDT
- SOLUSDT
- LINKUSDT
- AAVEUSDT

Both LONG and SHORT are evaluated.

### Partitioning

- exactly 10 chronological folds;
- causal closed candles only;
- identical frozen configuration in every fold and symbol;
- no fold-specific tuning;
- global fingerprint de-duplication across adjacent folds;
- the same event crossing a fold boundary counts once;
- independent event identity is based on the frozen P6 fingerprint/rearm contract.

### Counted observations

Only independent scenarios that reach `ENTRY_READY` with decision `VALID` or `HIGH_CONFIDENCE` are counted.

Excluded from the count:

- `NO_SETUP` and `WATCH`;
- duplicate fingerprints;
- re-emissions before valid rearm;
- scenarios failing economics or risk;
- expired, invalidated or cancelled scenarios;
- any observation whose provenance cannot be reconstructed exactly.

### Recognition gate

- PASS: at least 60 independent counted `ENTRY_READY` observations across the fixed universe, both directions and all 10 folds.
- FAIL: fewer than 60.

If FAIL, Candidate 1 is closed at recognition. Profitability, replay/freeze P8, holdout, paper and live are forbidden. No automatic loosening or second recognition attempt is permitted.

## Frozen output schema

Reports may include only:

- symbol, direction, fold, timestamp;
- scenario family, decision and lifecycle;
- fingerprint and rearm lineage;
- exact POI/liquidity/interaction/anchor/structure evidence IDs;
- economics/risk eligibility and block reasons without realized outcomes;
- aggregate recognition counts, block rates, duplicate rates and lifecycle diagnostics.

## Explicit prohibitions

No PnL, profitability, target-hit, stop-hit, future-return, MFE/MAE, drawdown, equity curve, trade simulation, holdout, paper trading, VPS execution or live orders are allowed in P7.
