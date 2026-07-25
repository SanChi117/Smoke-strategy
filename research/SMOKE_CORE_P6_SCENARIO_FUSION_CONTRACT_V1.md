# SMOKE CORE 1.0 — P6 Scenario Fusion Contract V1

## Scope

P6 fuses causal P1–P5 outputs into three independent family graphs. It is recognition-only and outcome-blind. It does not inspect PnL, MFE/MAE, exits or future bars.

## Families and frozen node weights

### LIQUIDITY_RAID_REVERSAL
Location 15; Raid 25; POI 15; Return/Acceptance 20; Structure 10; Economics 10; Risk 5.

### TREND_PULLBACK_CONTINUATION
Trend 20; POI 25; HTF protection 10; Mitigation 15; Resumption 15; Economics 10; Risk 5.

### RANGE_BOUNDARY_ROTATION
Range 20; Boundary liquidity 20; POI/Rejection 15; Acceptance 15; Space 20; Economics 5; Risk 5.

Each family totals 100. Family graphs are evaluated independently; the best family is never chosen retrospectively from trade outcomes.

## Evidence provenance

Evidence is grouped by `cluster_id`. Within a family node, cluster contribution is `primary + 0.35 * secondary_sum`, capped by the node maximum. One cluster cannot contribute to more than one node in the same scenario and cannot exceed 30 total scenario points. Derived evidence is not independent confirmation.

## Lifecycle

`DISCOVERED → ARMED → REACTION_DETECTED → CONFIRMED → ENTRY_READY → CONSUMED`, with terminal alternatives `EXPIRED`, `INVALIDATED`, `CANCELLED_BY_ECONOMICS`, `CANCELLED_BY_RISK`.

Lifecycle is monotonic. `ENTRY_READY` requires confirmed structure plus valid economics and risk. Hard causal/dependency failures map to `NO_SETUP`; economics and risk failures map to their cancellation states.

## Fingerprint and rearm

Fingerprint includes symbol, family, side, target level, POI, anchor and protected structure. Repeated evaluation of the same fingerprint cannot create a new setup. Rearm requires a new anchor, a new protected swing after a new reaction leg, or a new POI lifecycle identity.

## Decisions

- `NO_SETUP`: hard block or score < 60.
- `WATCH`: score 60–69 or lifecycle incomplete.
- `VALID_SETUP`: score 70–79 with economics and risk valid.
- `HIGH_CONFIDENCE_SETUP`: score >= 80 with economics and risk valid and no critical conflict.

## Prohibitions

No parameter tuning from market results. No recognition scan, profitability, holdout, paper, VPS execution or live trading in P6.