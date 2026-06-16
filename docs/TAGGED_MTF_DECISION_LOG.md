# Tagged MTF Decision Log

This document freezes the current tagged MTF research state so future changes do not drift into random filter tweaking.

## Current rule

Research/paper-review only. No live trading approval is implied by this file.

## Best current research baseline

`TAGGED_MTF_NO_DIRECTION_BLOCK_V1` is the current tagged MTF v2 baseline.

This is the HYBRID v2 branch from the controlled A/B comparison:

- allowed setup types: `pullback`, `ignition`
- allowed direction context: `down`
- blocked setup types: `breakout`, `range_rotation`, `watch_impulse`, `liquidity_reclaim`
- blocked volatility regimes: `high`
- blocked liquidity states: `high_sweep_reject`
- blocked candle types: `bear_rejection`
- blocked trend context: none

Best observed validation for this hybrid v2 baseline:

- tagged decision: `PROMOTE_TO_PAPER_REVIEW_CANDIDATE`
- paper-review status: `PAPER_REVIEW_READY`
- multi-WFO verdict: `PASS_STRONG_WFO`
- multi-WFO folds: `3/3`
- multi-WFO average return: `+0.6033%`
- multi-WFO average PF: `1.6331`
- multi-WFO worst DD: `3.69%`
- deep decision: `PASS_DEEP_STRONG`
- deep positive folds: `4/4`
- deep average return: `+4.915%`
- deep average PF: `1.9357`
- deep worst DD: `4.59%`
- deep executed trades: `264`

Paper-review interpretation:

- paper-review is ready under the protocol files generated in `results/tagged_universe_research/paper_review/`.
- live trading remains blocked.
- minimum review sample: 100 closed paper trades or 30 calendar days, whichever comes later.

## Controlled A/B branches

The suite still selects three legacy names for multi-WFO and deep validation. Their current intended mapping is:

1. `TAGGED_MTF_NO_DIRECTION_BLOCK_V1`
   - hybrid v2 baseline
   - no trend context block
   - keeps `pullback`/`ignition`
   - keeps `direction=down`
   - current best research baseline

2. `TAGGED_MTF_ENTRY_CONFIRM_V1`
   - strict v2 diagnostic
   - keeps strategy default trend-context block
   - keeps `pullback`/`ignition`
   - keeps `direction=down`

3. `TAGGED_MTF_NO_DIRECTION_NO_IGNITION_V1`
   - broad v2 diagnostic
   - no trend context block
   - no direction restriction
   - blocks `watch_impulse` and `liquidity_reclaim`

## Why broad v2 is not the baseline

Broad v2 can win a short matrix by having more trades, but it failed robustness checks in the controlled A/B artifact:

- multi-WFO verdict: `BLOCK_WEAK_WFO`
- positive folds: `1/3`
- average return: `+0.0767%`
- average PF: `1.1694`
- worst DD: `5.13%`

Therefore broad v2 remains diagnostic only.

## Do not do next

Do not keep adding filters from a single artifact without A/B comparison.
Do not manually pick winner symbols as a final solution.
Do not move to live trading from this decision log.
Do not treat a broader matrix with lower WFO quality as improvement just because it has more trades.

## Next acceptable step

Use the generated paper-review files:

- `paper_review_protocol.md`
- `paper_review_journal_template.csv`
- `paper_review_daily_checklist_template.csv`

Paper review must track every signal, rule violation, drawdown stop and context field before any further deployment discussion.
