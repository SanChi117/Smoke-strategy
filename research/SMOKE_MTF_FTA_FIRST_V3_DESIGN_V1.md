# SMOKE MTF FTA-FIRST V3 — Design V1

Status: `PREREGISTERED_IMPLEMENTATION_STARTED`

## Why V2 is closed

The frozen V2 development screen produced one accepted trade. The later outcome-blind funnel audit showed that the primary structural collapse was `ACTIVE_FTA_VALID -> RR_GATE_PASSED`: 429 structures had valid entry, stop, and FTA geometry, but only one reached RR 1.70. The secondary collapse was `POI_TESTED -> M5_BOS_CONFIRMED`.

V2 must not be tuned. Its thresholds and recognition semantics remain frozen and closed.

## Materially new V3 sequence

V3 changes the order of operations:

1. Confirm higher-timeframe directional context.
2. Select a real external 4H/1D/1W/1M FTA before any route is armed.
3. Require an active HTF POI.
4. Require either a fresh H1 raid or H1 VC followed by a later closed 15m test.
5. Confirm a causal 5m BOS after the route.
6. Wait for a later closed 15m pullback into the broken BOS pivot area.
7. Enter at the next aligned 15m open.
8. Place the stop behind a post-BOS protected 5m/15m swing, falling back only to the pullback wick.
9. Keep the preselected external FTA unchanged.
10. Require structural RR >= 1.70 and quality >= 55.

This is not a lower threshold version of V2. The target is selected first and the invalidation is rebuilt after BOS.

## Frozen recognition thresholds

- BOS body: at least 0.50 ATR.
- BOS close location: at least 0.70 in the directional part of the candle.
- BOS detection age: maximum 15 minutes.
- Pullback window: maximum 8 closed 15m bars after BOS.
- Pullback tolerance: 0.10 H1 ATR around the broken BOS pivot.
- Stop buffer: 0.10 H1 ATR.
- Minimum structural RR: 1.70.
- Minimum quality: 55.

## Outcome-blind gate

Before any profitability test:

- semantic replay must be exact;
- causal and accelerated runtimes must match;
- at least 60 independent `ENTRY_READY` structures must exist;
- duplicate snapshots of the same structural fingerprint count once;
- recognition core must be frozen at an exact SHA.

If fewer than 60 independent cases exist, V3 closes without profitability testing. No threshold adjustment is allowed from PnL or future price movement.

## Prohibited stages

Until recognition freeze: profitability, holdout, VPS, paper, and live are prohibited.
