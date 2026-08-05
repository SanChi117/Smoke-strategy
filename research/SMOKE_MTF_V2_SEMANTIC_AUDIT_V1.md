# SMOKE MTF V2 — Frozen Semantic Audit V1

## Scope

This audit uses only the closed-information semantic replay artifact from workflow run `29730284617` and the already frozen strategy definitions. No PnL, future return, TP/SL outcome, MFE or MAE was available or used.

- Source frozen recognition run: `29727847823`
- Semantic replay run: `29730284617`
- Semantic artifact id: `8456040400`
- Artifact digest: `sha256:3f8c31397e3c74ab05ed20a69c9bbd9c362bbd23e948ee6a0fcfd962c2b1763b`
- Frozen rows: 87
- Unique structural cases: 28
- Exact replay matches: 28
- Exact replay mismatches: 0
- Entry-ready cases before corrections: 0

## Definition-only findings

### 1. Raid invalidation used the reference pivot instead of the actual sweep extreme

Frozen contract: raid-path stop must be behind the swept fresh liquidity.

Observed completed raid chains:

| Case | Side | Reference pivot | Actual raid extreme | Planned stop |
|---|---|---:|---:|---:|
| AAVE 2025-02-03 03:15 | LONG | 204.00 | raid low 191.99 | 202.5254 |
| AAVE 2025-02-03 06:00 | LONG | 204.00 | raid low 191.99 | 202.3567 |
| LINK 2025-02-03 06:00 | LONG | 16.185 | raid low 15.429 | 16.0610 |
| BTC 2025-02-05 18:15 | SHORT | 98,914.4 | raid high 99,124.2 | 98,985.96 |

Every planned stop was inside the actual sweep candle. This is a structural-definition error independent of outcome. Correction: anchor raid stops to `raid_bar.low` for LONG and `raid_bar.high` for SHORT, plus the unchanged ATR buffer.

### 2. Target selection treated fully mitigated levels as active FTA/liquidity

Frozen contract: target is valid liquidity or FTA on the originating timeframe; level strength explicitly includes freshness and number of mitigations.

Observed completed chains selected extremely old, repeatedly mitigated levels as the first target, including:

- AAVE H1 bearish FVG at 230.30 with 9 recorded touches;
- LINK H1 high pivot near 18.1987 with 48 recorded touches;
- BTC H1 bullish FVG near 96,823.6 from an already repeatedly interacted area.

These are not active external liquidity/FTA under the frozen freshness/mitigation definition. Correction: mapped liquidity levels must be fresh to qualify as directional targets. Timeframe-matched weak/range extremes remain deterministic fallbacks.

### 3. Diagnostic nearest support/resistance ignored the stored level side

The context helper classified any level below price as support and any level above price as resistance. Replay packets therefore contained examples where `nearest_support.side == resistance` and `nearest_resistance.side == support`.

This helper was primarily diagnostic, but the payload was semantically false. Correction: nearest support only considers `side == support`; nearest resistance only considers `side == resistance`.

## Explicit non-findings

The audit did not use future outcomes to change:

- `min_rr = 1.70`;
- minimum quality score;
- BOS body/close-location requirements;
- H1 raid freshness;
- VC displacement or later 15m retest rules;
- timeframe roles;
- five-symbol universe;
- frozen history or recognition scan;
- chronological sample rule.

The 1D/4H weighted context conflict policy remains unchanged because the replay did not prove a definition mismatch against the frozen contract.

## Required verification after correction

1. New regression tests must fail on the old implementation and pass on the corrected implementation.
2. Cached and ordinary runtime plans must remain exactly equivalent.
3. Re-run the same five-symbol, same-period, no-PnL recognition contract.
4. Rebuild the same closed-information semantic replay.
5. Only after exact replay and semantic review may recognition-core be frozen.
6. Profitability development remains forbidden until explicit freeze.
