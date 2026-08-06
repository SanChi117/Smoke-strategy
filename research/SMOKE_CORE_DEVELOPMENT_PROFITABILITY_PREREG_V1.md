# SMOKE CORE 1.0 — Candidate 1 Development Profitability Preregistration V1

## Fixed identity

- Test ID: `SMOKE_CORE_CANDIDATE_1_DEVELOPMENT_PROFITABILITY_FIXED_V1`
- Candidate ID: `SMOKE_CORE_1_0_CANDIDATE_1`
- Frozen P8 authoritative SHA: `eef6bf319f53e4434d5f99bf54bc7f78c1b41f75`
- P8 ID: `SMOKE_CORE_P8_SEMANTIC_REPLAY_FREEZE_FIXED_V1`
- P8 freeze manifest SHA-256: `8fa00da7f22c70ddd48208a3cdcf678d540f29738bbff6ef9978f72477e4b429`
- P7 recognition ID: `SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1`

This document is committed before reading any development-profitability result. Exactly one authoritative test is permitted. No threshold, score, weight, lifecycle, evidence, fingerprint, rearm, cost, risk, portfolio, entry, stop or target rule may be changed after results are read.

## Development sample

The development sample is exactly the same locked Binance Vision USD-M Futures closed-candle dataset used by P7/P8:

- source: Binance Vision USD-M Futures;
- interval: 5m canonical closed candles;
- start inclusive: `2024-01-01T00:00:00+00:00`;
- end inclusive: `2024-06-30T23:55:00+00:00`;
- symbols, in frozen order: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LINKUSDT`, `AAVEUSDT`;
- directions: LONG and SHORT;
- exactly 10 contiguous chronological folds;
- global fingerprint de-duplication before portfolio admission.

No external holdout data may be read in this phase.

## Signal and execution semantics

The test must use the exact P8-frozen Candidate 1 implementation and exact P1-P8 semantic files at the authoritative SHA. Candidate generation, decision thresholds, evidence anti-double-counting, lifecycle, fingerprint/rearm, entry, structural stop, selected target, costs, leverage, isolated margin, 0.5% position risk, 2% total open-risk cap, notional/margin limits, liquidation-safety checks and correlation-cluster ranking are unchanged.

Only independent globally de-duplicated `VALID_SETUP` or `HIGH_CONFIDENCE_SETUP` scenarios in lifecycle `ENTRY_READY` are eligible. No later signal may retroactively alter an earlier entry, stop or target.

## Fill and outcome convention

- Entry is filled only at the frozen causal entry timestamp and frozen entry price.
- The trade is evaluated using subsequent closed 5m candles only.
- Stop and target are fixed at admission and never moved.
- If stop and target are both reachable within the same 5m candle, the stop is applied first (`STOP_FIRST`).
- Gap-through execution is conservative: an adverse gap fills at the first available candle open if worse than the stop; a favorable gap does not improve the frozen target fill.
- Round-trip fees, slippage, funding and explicit cost buffer use the frozen P5 cost model. Returns are reported after all costs.
- No trailing, partial exits, averaging, DCA, discretionary exit or outcome-dependent cancellation is allowed.
- Positions still open at the development sample end are force-closed at the final available close after all applicable costs and are included in metrics.

## Portfolio simulation

Trades are processed in strict causal timestamp order. Ties use frozen deterministic correlation-cluster ranking and then symbol/direction/fingerprint ordering. The exact P5 portfolio constraints apply at entry. Rejected overlapping candidates are not re-entered later unless the frozen P6 rearm contract independently emits a new eligible fingerprint.

Equity starts at 1.0 normalized unit. Position risk is based on current causal equity. No deposits, withdrawals, tuning or fold-specific parameter changes are allowed.

## Prespecified metrics

The report must include:

- total closed trades;
- gross profit, gross loss and pooled profit factor;
- arithmetic average net trade return after all costs;
- per-fold net return and count of positive folds;
- maximum peak-to-trough equity drawdown;
- counts by symbol, direction, family, fold and exit reason;
- ambiguity count resolved by `STOP_FIRST`;
- portfolio rejections by frozen reason;
- exact source/freeze identifiers and deterministic report hash.

## Formal gate

Candidate 1 passes development profitability only when every condition is true:

1. total closed trades `>= 60`;
2. pooled profit factor `>= 1.20`;
3. arithmetic average net trade return after all costs `> 0`;
4. at least `6` of `10` folds have positive net return;
5. maximum drawdown `<= 8.00%`.

Any failed condition is a formal `FAIL`. A failure closes Candidate 1 without tuning, second recognition, relaxed rule, alternate cost model or second development test.

A `PASS` permits preparation of one untouched external holdout preregistration only. It does not permit paper, live, VPS execution or real orders.

## Integrity requirements

The runner and workflow must verify before execution:

- checked-out semantic files match the P8 freeze manifest;
- fixed universe, directions, period and 10-fold partition are exact;
- globally de-duplicated eligible input is deterministic;
- the report contains outcome fields only in this explicitly permitted profitability artifact;
- no external holdout file, paper service, exchange API or live-order module is imported or called;
- the authoritative workflow executes the profitability evaluator exactly once.
