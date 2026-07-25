# SMOKE CORE 1.0 — P3 Interaction Engine Contract V1

## Scope

P3 is an outcome-blind recognition layer. It converts exact closed-candle interaction with P1 POIs and P2 liquidity levels into causal events, explicit relations and anchor events. P3 does not create entries, stops, targets, RR, sizing, PnL or trade outcomes.

## Inputs

- closed candles for the requested execution timeframe;
- P1 `POIZone` objects confirmed no later than `evaluated_at`;
- P2 `LiquidityLevelV1` objects confirmed no later than `evaluated_at`;
- exact POI ids, liquidity ids, evidence ids and evidence-cluster ids.

## Outputs

- interaction events: `MITIGATION`, `SWEEP`, `REJECTION`, `ACCEPTANCE`;
- event lifecycle: `DISCOVERED`, `CONFIRMED`, `EXPIRED`, `INVALIDATED`;
- explicit relations: `INDUCEMENT_TO_REACTION`, `VICTIM_CANDLE_TO_REACTION`;
- anchors: `LIQUIDITY_SWEEP`, `POI_REJECTION`, `LEVEL_ACCEPTANCE`;
- no-outcome snapshot export.

## Frozen semantics

1. A relationship is valid only when it points to an exact `source_poi_id` or `source_liquidity_id`.
2. Temporal proximity alone must never create a POI/liquidity relation.
3. A liquidity sweep requires an excursion beyond the exact level and a closed return through the configured buffer.
4. Acceptance requires two consecutive closed candles beyond the exact level and buffer.
5. A POI rejection requires exact zone touch, directional close, minimum wick/body ratio and minimum close location.
6. A mitigation touch is descriptive and cannot itself become an execution anchor.
7. A victim candle relation requires the immediately preceding opposite candle to touch the same POI.
8. An inducement relation requires a prior exact liquidity sweep, matching direction, temporal order, bounded age and spatial relation to the same POI reaction.
9. Event invalidation requires two consecutive closes beyond the exact source zone in the adverse direction.
10. Events expire after a frozen number of source-timeframe bars. No retroactive fill or future information is allowed.
11. One semantic kind is emitted at most once per exact source id in one snapshot.
12. P3 must preserve P1/P2 provenance and may not convert derived evidence into independent evidence.

## Frozen defaults

- ATR length: 14;
- touch buffer: 0.03 ATR;
- minimum raid excursion: 0.03 ATR;
- return-close buffer: 0.02 ATR;
- acceptance buffer: 0.05 ATR;
- acceptance closes: 2;
- rejection wick/body ratio: 1.50;
- rejection close location: 0.60;
- invalidation buffer: 0.05 ATR;
- invalidation closes: 2;
- anchor expiry: 6 source-timeframe bars;
- inducement maximum age: 12 source-timeframe bars;
- inducement maximum spatial distance: 1.00 ATR.

## Hard blocks

Only these conditions may hard-block P3:

- no closed candles at or before `evaluated_at`;
- no causal P1 POI or P2 liquidity source.

No interaction found is a valid outcome-blind result and is not itself a hard block.

## Required semantic tests

- buy-side and sell-side exact sweep;
- no sweep from a merely nearby bar;
- two-close acceptance;
- exact POI rejection;
- victim candle tied to the same POI;
- mitigation is not an anchor;
- anchor preserves exact dependency id;
- inducement requires temporal and spatial linkage;
- far liquidity is not linked;
- expiry after the frozen window;
- two-close adverse invalidation;
- missing-source hard block;
- no-PnL/outcome export guard;
- P1 and P2 regression suites remain green.

## Exit gate

P3 is complete only when compile, all P3 semantic tests, P2 regression tests, P1 regression tests, completeness guard and no-outcome guard are green. P4 is forbidden before this gate.