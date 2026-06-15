# Tagged MTF Decision Log

This document freezes the current tagged MTF research state so future changes do not drift into random filter tweaking.

## Current rule

Research/paper-review only. No live trading approval is implied by this file.

## Best current research baseline

`TAGGED_MTF_ENTRY_CONFIRM_V1` is the current strict MTF v2 baseline.

In the fast matrix file this legacy name intentionally maps to:

- allowed setup types: `pullback`, `ignition`
- allowed direction context: `down`
- blocked setup types: `breakout`, `range_rotation`, `watch_impulse`, `liquidity_reclaim`
- blocked volatility regimes: `high`
- blocked liquidity states: `high_sweep_reject`
- blocked candle types: `bear_rejection`
- trend context block: left as the strategy default

Best observed deep validation for this strict v2 baseline:

- decision: `PASS_DEEP_STRONG`
- positive folds: `4/4`
- average return: `+4.3%`
- average PF: `1.8743`
- worst DD: `4.07%`
- executed trades: `254`

Paper-review interpretation:

- paper-review can be considered only with caution
- live trading remains blocked
- reason: Multi-WFO / matrix were still weak and overfiltered in the same artifact

## Diagnostic branches

The suite still selects three legacy names for multi-WFO and deep validation. Their current intended mapping is:

1. `TAGGED_MTF_ENTRY_CONFIRM_V1`
   - strict MTF v2 baseline
   - current best research baseline

2. `TAGGED_MTF_NO_DIRECTION_NO_IGNITION_V1`
   - broad v2 diagnostic
   - no trend context block
   - blocks `watch_impulse` and `liquidity_reclaim`
   - no direction restriction

3. `TAGGED_MTF_NO_DIRECTION_BLOCK_V1`
   - hybrid v2 diagnostic
   - no trend context block
   - keeps `pullback`/`ignition`
   - keeps `direction=down`

## Why the trend-context fix is not the new baseline

The trend-context free test removed the apparent conflict between:

- `blocked_trend_contexts=down`
- `allowed_direction_contexts=down`

That test increased matrix trade count but reduced deep quality.

Observed after freeing trend context:

- deep decision: `PASS_DEEP_STRONG`
- positive folds: `4/4`
- average return: `+2.91%`
- average PF: `1.4469`
- worst DD: `5.14%`
- executed trades: `302`

This is weaker than the strict baseline. Therefore the trend-context free version is diagnostic only, not the new baseline.

## Do not do next

Do not keep adding filters from a single artifact without A/B comparison.
Do not manually pick winner symbols as a final solution.
Do not move to live trading while Multi-WFO remains weak.
Do not treat a broader matrix with lower PF as improvement just because it has more trades.

## Next acceptable step

Run the three-branch A/B test above and compare:

- matrix trades
- Multi-WFO folds
- Deep folds
- average PF
- worst DD
- paper-review status

A branch can replace the strict baseline only if it improves robustness without materially degrading deep PF/DD.
