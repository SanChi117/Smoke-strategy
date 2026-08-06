# SMOKE CORE 1.0 — P9 Development Profitability Preregistration V1

## Status and authority

This document is committed before any P9 outcome report exists.

Authoritative frozen recognition source:

- candidate: `SMOKE_CORE_1_0_CANDIDATE_1`;
- P7 recognition run: `30899050584`;
- P7 head: `b749be2578251a3b447a78a79009ff3d45cffc57`;
- P7 independent counted `ENTRY_READY`: `2620`;
- P8 semantic replay run: `31004476021`;
- P8 head: `eef6bf319f53e4434d5f99bf54bc7f78c1b41f75`;
- P8 artifact digest: `sha256:89a497b9a3dbe79ece05440bd56a365dda410b324c41399420c89aab22b8ec3b`;
- P8 causal canonical rows: `4053`;
- P8 fast canonical rows: `4053`;
- P8 `mismatch_count = 0`;
- P8 freeze manifest complete: `26/26` required files.

No P1–P8 semantic rule, threshold, score weight, lifecycle rule, evidence lineage, fingerprint, rearm rule, target selection rule, protected-swing rule, universe, period or fold assignment may be changed in P9.

## Purpose

P9 is one development-sample profitability evaluation of the exact frozen Candidate 1 semantics. It answers only whether the already frozen recognized setups have positive net expectancy under a predefined executable fill model, the existing P5 costs, and the existing P5 risk and portfolio limits.

P9 is not holdout validation, not parameter optimization, not paper trading and not live authorization.

## Frozen data scope

- source: the exact authoritative P7 locked Binance Vision artifact from run `30899050584`;
- interval: 5-minute closed OHLCV;
- symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LINKUSDT`, `AAVEUSDT`;
- start inclusive: `2024-01-01T00:00:00+00:00`;
- end inclusive open time: `2024-06-30T23:55:00+00:00`;
- directions: `LONG`, `SHORT`;
- chronological folds: exactly `10`;
- this entire period is development data and must never be described as holdout.

## Recognition parity gate

Before outcomes are calculated, P9 must reproduce the exact globally deduplicated counted recognition set:

- counted records: exactly `2620`;
- exact fingerprint set equality with the authoritative P7 report;
- no missing counted record;
- no extra counted record;
- no duplicate selected record;
- exact symbol, direction, fold, timestamp, family, lifecycle, decision and provenance identity for every selected record.

Any parity failure makes P9 technically invalid. Profitability numbers from an invalid run must not be interpreted.

## Geometry capture contract

P9 may observe, but must not replace, the frozen P7 `_build_observation` execution path.

A non-mutating transport wrapper records the exact objects already passed through the frozen implementation:

- reference entry price;
- frozen protected-swing stop price;
- frozen target price and target id;
- exact P5 `ExecutionCandidate`;
- exact P5 admission result and net RR;
- final P6 score and decision;
- dependency and provenance ids.

The wrapper must call the original frozen functions and must assert one captured geometry record for each emitted recognition observation. Geometry capture may not alter return values or branching.

## Executable entry model

Recognition timestamp is the earliest time at which the setup is known.

For every selected counted setup:

1. Find the first locked 5-minute candle whose open time is greater than or equal to the recognition timestamp.
2. Use that candle open as the raw executable market price.
3. Apply adverse entry slippage from the frozen P5 `CostModel`:
   - LONG entry: raw open × `(1 + 0.02%)`;
   - SHORT entry: raw open × `(1 - 0.02%)`.
4. Do not assume a fill at an earlier reference price.
5. Do not use limit-order hindsight.
6. If no eligible 5-minute candle exists, classify `NO_FUTURE_BAR`.
7. If the executable fill is already at or through the frozen stop or target, classify `NON_EXECUTABLE_GAP`.

`NO_FUTURE_BAR` and `NON_EXECUTABLE_GAP` are not silently removed. They are reported and are not eligible for portfolio execution.

## Frozen exit model

- Stop and target remain fixed at the exact frozen geometry prices.
- No trailing stop.
- No partial close.
- No breakeven move.
- No averaging.
- No re-entry beyond the frozen global fingerprint/rearm semantics.
- Maximum holding horizon: `576` five-minute candles, equal to 48 hours.
- The entry candle is candle 1 of the holding horizon.
- If stop and target are both touched in the same candle, apply the conservative rule `STOP_FIRST`.
- If neither level is touched by candle 576, exit at that candle close with reason `TIME_EXIT`.
- If the locked dataset ends first, exit at the last available candle close with reason `END_OF_DATA`.

Adverse exit slippage from the frozen P5 `CostModel` is applied:

- LONG exit: raw exit × `(1 - 0.02%)`;
- SHORT exit: raw exit × `(1 + 0.02%)`.

## Frozen costs

Use the existing P5 `CostModel` without tuning:

- entry fee: `0.04%`;
- exit fee: `0.04%`;
- entry slippage: `0.02%` through executable fill price;
- exit slippage: `0.02%` through executable exit price;
- expected funding: `0.01%` of initial notional per executed position;
- cost buffer: `0.02%` of initial notional per executed position.

Fees are charged on actual entry and exit notionals. Funding and cost buffer are explicit fixed deductions. Slippage must not be deducted twice.

## MAE, MFE and time measurements

For each executable setup, calculate from entry until exit using only subsequent locked 5-minute bars:

- gross and net return;
- net R multiple;
- MAE percentage;
- MFE percentage;
- bars held;
- minutes held;
- exit reason;
- same-bar ambiguity count.

These fields are allowed only in P9 outcome artifacts and must never be copied back into P1–P8 recognition artifacts.

## Frozen risk and portfolio simulation

Initial equity: `10000.00` quote currency units.

Use the existing P5 `RiskLimits` without tuning:

- risk per position: `0.5%` of current realized equity;
- maximum total open risk: `2.0%`;
- default leverage: `20x`;
- maximum leverage: `25x`;
- isolated margin required;
- maximum margin per position: `10%` of current equity;
- maximum total margin: `25%` of current equity;
- maximum total notional: `2.5x` current equity;
- minimum net RR: `1.35`;
- preferred net RR: `1.70`.

Position notional is calculated exactly as P5 does:

`risk_amount / reference_stop_distance_fraction`.

Open positions are not resized after admission.

All Candidate 1 records use the frozen `CRYPTO_MARKET_BETA` correlation cluster. Portfolio capacity is enforced across all symbols and directions.

At an identical timestamp:

1. Process exits at that timestamp before new admissions.
2. Rank new candidates by:
   - `HIGH_CONFIDENCE_SETUP` before `VALID_SETUP`;
   - higher exact P5 net RR;
   - higher exact final P6 score;
   - lower margin percentage;
   - lexical fingerprint tie-break.
3. Admit in that fixed order while all P5 portfolio limits remain satisfied.

Capacity rejection is reported as `REJECT_PORTFOLIO_CAPACITY`; it is not counted as a losing trade.

Realized equity is updated at each exit. When multiple exits have the same timestamp, process them by lexical fingerprint for deterministic reproducibility.

## Primary report

P9 must produce both:

1. independent signal-outcome diagnostics for every executable globally deduplicated counted setup;
2. one chronological portfolio realization under the frozen limits above.

Required portfolio metrics:

- eligible, executed and capacity-rejected counts;
- ending equity;
- total net return percentage;
- net expectancy per executed trade in percentage and R;
- profit factor;
- win rate;
- maximum realized-equity drawdown percentage;
- gross profit and gross loss;
- average and median net R;
- stop, target, time-exit and end-of-data counts;
- average MAE, MFE and holding time;
- results by symbol, direction, family and fold;
- positive-expectancy symbol count;
- positive-expectancy fold count;
- positive gross-profit concentration by symbol;
- deterministic report digest.

## Frozen P9 development gate

P9 status is `PASS` only if every condition is true:

1. recognition parity is exact and valid;
2. at least `200` portfolio trades are executed;
3. ending equity is greater than starting equity;
4. portfolio net expectancy R is strictly greater than `0.00`;
5. portfolio profit factor is at least `1.10`;
6. maximum realized-equity drawdown is no greater than `15.0%`;
7. at least `3` of `5` symbols have positive net expectancy R;
8. at least `6` of `10` folds have positive net expectancy R;
9. at least `50` LONG and `50` SHORT positions are executed;
10. no single symbol contributes more than `60%` of total positive gross profit;
11. there are no unexplained missing geometries, duplicate selected records or non-deterministic report fields.

No metric may be removed, reweighted or relaxed after results are known. A failed gate is a valid research result, not permission to tune Candidate 1 on the same sample.

## Reproducibility

The output must include SHA-256 hashes of:

- this preregistration;
- P8 semantic freeze report and manifest;
- authoritative P7 report;
- locked data manifest;
- all source and test files introduced by P9;
- the canonical selected geometry stream;
- the canonical outcome stream;
- the final report.

The same inputs must produce byte-stable canonical JSON and the same report digest.

## Permitted next step

- If P9 is `PASS`: the next permitted activity is a separately preregistered untouched holdout evaluation. Candidate 1 remains frozen.
- If P9 is `FAIL`: holdout, paper, live, VPS deployment and real orders remain prohibited. Any revised Candidate 2 must receive a new id and restart the required recognition, semantic replay and development evaluation chain.

No paper trading, live trading, VPS deployment or real order execution is authorized by this document.
