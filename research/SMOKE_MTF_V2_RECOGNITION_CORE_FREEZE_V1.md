# SMOKE MTF V2 — Recognition Core Freeze V1

## Freeze decision

The recognition and entry-definition core is frozen for the first development profitability screen.

- Frozen repository SHA: `492eee9fdba5993b7f518e9a1ff38576e8b14285`
- Last semantic-definition correction commit: `251e6e150768673e8e2cdcd3f52124b5485aade2`
- Frozen real-recognition run: `29847860881`
- Frozen combined artifact: `smoke-mtf-v2-real-recognition-v1-combined`
- Frozen combined artifact id: `8502319570`
- Frozen combined artifact digest: `sha256:a1a1edc234c2fb2363391e8239869f3a0f72e04c2aad87c551e413a47c44ee0e`
- Semantic replay run: `29852278087`
- Semantic replay artifact: `smoke-mtf-v2-semantic-replay-v1`
- Semantic replay artifact id: `8503935998`
- Semantic replay artifact digest: `sha256:bcb645fddec649b938b6ac069b3754faa5c458c91cb9d717600aa1dab1f84568`

## Validation result

- Frozen rows: **87**
- Unique structural cases: **28**
- Exact replay matches: **28/28**
- Exact replay mismatches: **0**
- Entry-ready cases in the frozen recognition week: **0**
- No-PnL / no future-outcome fields: **PASS**
- Evaluation order: chronological within each symbol
- Execution geometry: independent engine per symbol

The absence of `ENTRY_READY` cases in the frozen recognition week is not a profitability conclusion. It is retained as observed recognition evidence and may not be used to loosen thresholds.

## Frozen definitions

1. All source features use only fully closed candles.
2. Pivots/fractals become available only after their right-side confirmation candles close.
3. Context hierarchy is `1M → 1W → 1D → 4H`.
4. Entry routes are limited to:
   - fresh closed H1 liquidity raid → later confirmed 5m BOS;
   - H1 volume confirmation after HTF POI contact → new VC zone → later closed 15m zone test → later confirmed 5m BOS.
5. A simple H1 reaction candle is diagnostic only.
6. BOS requires a body close beyond a pivot known before the signal candle opened.
7. Execution uses only the next aligned 15m bar open.
8. Raid-path invalidation is behind the actual swept wick extreme plus the frozen ATR buffer.
9. VC-path invalidation is behind a qualifying structural Strong High/Low or POI invalidation.
10. Fully mitigated liquidity-map levels cannot act as active FTA targets.
11. Target selection remains timeframe-matched to the originating raid/POI route.
12. Minimum structural RR remains `1.70`.
13. Minimum quality score remains `55.0`.
14. High-impact event blackout remains a hard entry block.

## Prohibited changes during the development screen

The following are prohibited after any development PnL result is viewed:

- changing thresholds, symbols, timeframes, state transitions or target/stop definitions;
- adding or removing filters based on trade outcomes;
- changing the fee, slippage or portfolio model;
- selecting folds, symbols or periods based on performance;
- using the exposed development period as the external holdout;
- opening paper, VPS or live trading before the required gates pass.

Any later technical correction must prove that it fixes execution, data integrity or causal equivalence only. A semantic rule change creates a new strategy version and invalidates this freeze.

## Allowed next step

Only the preregistered development profitability screen in `research/smoke_mtf_v2_development_profitability_prereg_v1.json` may follow. The screen must not start until CI for the commit containing this freeze document and preregistration is green.
