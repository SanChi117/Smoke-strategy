# SMOKE CORE 1.0 — P1 POI / Imbalance Contract V1

Status: `IMPLEMENTATION_STARTED_NO_PNL`

## Authority

This package implements P1 from `SMOKE_Master_TZ_v1.1_RU.docx` and `SMOKE_P0_Formal_Spec_v0.1_RU.docx`.
V2/V3 trading rules are closed. Only causal closed-candle and confirmed-pivot infrastructure may be reused.

## Scope

P1 implements:

- origin-of-displacement POIs;
- three-candle FVG / imbalance POIs;
- evidence provenance and parent/derived relations;
- evidence-cluster diminishing returns;
- deterministic overlapping composite zones;
- lifecycle `CANDIDATE → ACTIVE → TESTED → PARTIALLY_MITIGATED → INVALIDATED`;
- freshness, mitigation, age, location and liquidity-relation score components;
- no-PnL serialization.

P1 does not implement entries, stops, targets, RR, sizing, profitability, paper or live orders.

## Causality

- Read only bars with `close_time <= evaluated_at`.
- Origin POI confirms at the displacement candle close.
- FVG confirms only after the third candle closes.
- Structural consequence may use only pivots confirmed before the displacement opens.
- LTF reactions never create HTF POIs retroactively.
- Identical closed-bar input must create identical IDs.

## Evidence provenance

A displacement, its origin, FVG, structure break and volume expansion are one causal evidence cluster.
The displacement is `PRIMARY`; its consequences are `DERIVED` and share `parent_event_id`.
Cluster contribution uses `primary + 0.35 × secondary_sum` and is capped at 30 later scenario-score points.

## Frozen P1 defaults

- displacement body >= `0.55 ATR`;
- full range >= `0.85 ATR`;
- close location >= `0.67`;
- optional volume expansion >= `1.35` relative volume;
- origin search = 4 closed bars;
- origin envelope = body plus 25% wick extension;
- FVG width >= `0.08 ATR`;
- composite overlap >= 20% of smaller zone;
- partial mitigation >= 50%;
- invalidation = 2 consecutive closes outside zone plus `0.05 ATR` buffer.

## Quality components

- displacement 25%;
- structural consequence 20%;
- imbalance quality 15%;
- freshness 15%;
- location 10%;
- liquidity relation 10%;
- age 5%.

Location and liquidity relation are external P2 modifiers and cannot be invented by P1.

## Semantic gate

The P1 test suite must prove bullish/bearish formation, separate origin/FVG confirmation time, no retroactivity, deterministic IDs, provenance, diminishing returns, composite merge, lifecycle transitions, acceptance invalidation, external modifiers and no-outcome serialization.

## Forbidden outputs

No PnL, future return, trade outcome, TP/SL outcome, MFE/MAE, profit factor, net return, drawdown or exit price.

## Next gate

P2 Context / Liquidity Engine may start only after P1 CI is green. No recognition or profitability run is authorized by P1.
