# SMOKE VALIDATION AUDIT R1

## Purpose

Audit the current Smoke Strategy research stack without changing trading logic.

The goal is to separate:

1. market/entry primitives;
2. adaptive post-filters;
3. risk/portfolio controls;
4. validation methodology;
5. any look-ahead or selection leakage.

This branch is research-only. It must not change live/PAPER behavior.

## Current mechanism map

### Market primitives

- 1D/4H MTF trend context
- volatility regime
- volume state
- Donchian/range position
- candle impulse/rejection
- liquidity sweep/reclaim
- breakout continuation
- pullback
- range rotation
- ignition

These are candidate edge primitives. They must be evaluated separately before being treated as proven components.

### Adaptive post-filters

- Rolling Symbol Strength
- Trade Quality Score
- Structure Learning

These modules are not independent edge sources. All three consume realized historical trade outcomes such as PF, average R, win rate, sample size and/or loss streak, then transform those statistics into rankings or TAKE/WATCH/SKIP decisions.

### Risk / portfolio controls

- setup-aware stop distance and target RR
- confidence-based risk grade
- per-trade risk sizing
- leverage and margin limits
- max positions and symbol concentration
- daily/weekly loss halts
- fees/slippage

These may improve risk-adjusted behavior but are not evidence of directional edge by themselves.

## Confirmed validation problems

### 1. Full-sample universe look-ahead

The default integrated pipeline calls `rank_universe(all_trades)` before historical decisions are evaluated. `universe_selector` ranks symbols using realized PF / avgR / winrate / loss streak from the complete supplied trade set.

When `require_universe_gate=True`, early historical trades can therefore be filtered using outcomes that occur later in the same test period.

This is direct look-ahead and invalidates any profitability claim that depends on the default learned-universe gate.

`TACTICAL_CORE_DIRECT_MICRO_STRICT` has `require_universe_gate=false`, so this particular leakage does not apply to that baseline.

### 2. Matrix selection leakage

`promote_matrix_baseline.py` sorts the matrix by research score and promotes the best row.

If the same historical period is then split into validation folds, those folds are not untouched because the selected parameter/filter combination has already been chosen using the aggregate period.

This is model-selection leakage unless matrix selection is performed inside each outer training fold.

### 3. Warmup contamination in walk-forward metrics

`run_binance_walk_forward.py` writes candles from `warmup_start` through `validation_end`, then sets `PipelineConfig.start=warmup_start` and reports the end-to-end summary directly.

The reported return, PF, drawdown and executed trade count therefore include the warmup/training interval, not only `validation_start -> validation_end`.

`run_binance_walk_forward_v2.py` explicitly preserves the base fold execution behavior, so the same issue remains in v2.

Consequently historical `3/3` or `4/4` positive WFO claims cannot be treated as clean OOS evidence until re-run with validation-only scoring.

## Parts that are structurally sound

- Candle exits use future candles only after entry.
- If SL and TP are both touched in the same candle, SL is counted first.
- Rolling Symbol Strength uses a backward rolling window and then applies the ranking to the following rebalance interval.
- Trade Quality Score uses prior same-symbol trades inside its lookback window.
- Structure Learning maintains rolling prior history and scores the current trade before appending it.

These mechanisms still require efficacy tests, but their core temporal ordering is causal.

## R1 corrected validation rules

### Fixed-baseline audit

For an already frozen baseline:

1. include warmup candles before each validation interval;
2. generate features, candidates and adaptive filter states using warmup + validation data;
3. allow warmup trades to train rolling/quality/structure state;
4. exclude every trade with `entry_time < validation_start` from performance metrics;
5. start portfolio equity fresh at the validation boundary;
6. report only validation-period trades, fees, PF, return and DD.

This fixes warmup contamination but does not remove historical matrix-selection leakage.

### True nested walk-forward

For clean strategy selection:

1. define chronological outer folds;
2. within each outer training section, run the matrix and choose a winner using training data only;
3. freeze that winner before the outer validation section;
4. carry only causal warmup/state into validation;
5. score performance exclusively on outer validation trades;
6. never use future symbol PF/avgR to build the universe;
7. aggregate outer-fold results only after all fold decisions are frozen.

## Universe rule for corrected tests

Allowed options:

- explicit predeclared symbol universe;
- causal rolling selector using only prior observations;
- liquidity/history filters based only on information available before each decision.

Disallowed:

- `rank_universe(all_trades)` followed by application of that ranking to earlier trades in the same sample.

## Interpretation of current SMOKE evidence

Current high PF / WFO snapshots are useful as hypothesis-generation evidence, not final proof.

The most valuable next question is not whether the whole multilayer stack is profitable. It is:

> Which primitive still has positive expectancy after corrected nested validation, before adaptive outcome-based filters are added?

## Next implementation step

Add a corrected fixed-baseline WFO runner that preserves warmup state but calculates portfolio metrics only from validation-period entries. Then run `TACTICAL_CORE_DIRECT_MICRO_STRICT` through it as an audit control.

After that, implement nested matrix selection for a truly clean outer walk-forward test.
