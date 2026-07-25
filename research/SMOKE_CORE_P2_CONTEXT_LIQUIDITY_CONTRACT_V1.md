# SMOKE CORE 1.0 — P2 Context / Liquidity Contract V1

## Scope

P2 is a recognition-only layer. It describes the market environment and builds a causal liquidity/target map. It does not create entries, stops, position sizes, trade outcomes or PnL.

## Inputs

- closed 5m source candles;
- causal 15m/1h/4h/1d/1w/1M aggregates from `MtfDealingRangeEngine`;
- confirmed pivots/fractals only after right-side candles close;
- P1 `Direction` enum;
- previous fully closed day/week/month levels.

## Parallel outputs

1. Per-timeframe state for 1M/1W/1D/4H/1H:
   - direction;
   - market state;
   - confidence;
   - dealing range and premium/discount;
   - protected/weak levels;
   - ATR percentage and volatility regime.
2. Aggregate macro direction and regime.
3. Liquidity map:
   - confirmed swings;
   - equal highs/lows;
   - PDH/PDL, PWH/PWL, PMH/PML;
   - completed session highs/lows;
   - 4H/1D dealing-range extremes.
4. Causal level lifecycle:
   - `FRESH`;
   - `PARTIALLY_MITIGATED`;
   - `SWEPT`;
   - `INVALIDATED`.
5. Pre-ranked LONG and SHORT target candidates.

## Frozen semantics

- HTF conflict is a soft conflict and confidence penalty, not an automatic hard block.
- A level is unavailable before its source event is confirmed.
- Equal highs/lows use ATR known at the second pivot confirmation; no current/future ATR may retroactively create them.
- A wick beyond liquidity followed by a close back is a sweep.
- Invalidation requires two consecutive closes beyond an ATR buffer.
- Swept and invalidated levels are excluded from target candidates.
- External targets are ranked before internal targets, then by distance and strength.
- Target ranking does not use RR, PnL, future returns or trade outcomes.
- Session levels appear only after a complete UTC session window closes.
- Range-level IDs use the causal dealing-range confirmation timestamp, not the current snapshot timestamp.

## Frozen defaults

- ATR length: 14;
- volatility lookback: 20;
- expansion ratio: 1.35;
- compression ratio: 0.75;
- macro direction threshold: 0.15;
- equal-level tolerance: max(0.12 ATR, 0.12% price);
- equal pivot minimum separation: 2 bars;
- sweep buffer: 0.03 ATR;
- invalidation buffer: 0.05 ATR;
- invalidation closes: 2;
- context weights: 1M 0.10, 1W 0.20, 1D 0.35, 4H 0.35;
- sessions UTC: Asia 00:00–08:00, London 08:00–13:00, New York 13:00–21:00.

## Hard blocks

Only insufficient closed market data or insufficient macro context can hard-block P2. Direction conflict, range state, compression and weak levels are reported as features/conflicts.

## Required tests

- macro conflict penalty without hard block;
- insufficient context;
- causal timeframe state;
- completed-session requirement;
- buy-side and sell-side sweep;
- two-close invalidation;
- exclusion of swept/invalidated targets;
- external-before-internal ranking;
- no RR input to target selection;
- deterministic IDs;
- no-PnL/outcome serialization guard;
- reused causal pivot/period-level tests.

## Exit gate

P2 is complete only when compile, P2 semantic tests, P1 semantic tests, reused causal primitive tests and frozen-contract guard are all green. P3 is forbidden before this gate.
