# SMOKE Research Ladder — Final Conclusion V1

Date: 2026-07-18

Status: **EXHAUSTED_WITHOUT_ROBUST_EDGE**

Research branch: `agent/live-paper-hardening`

## Completed preregistered ladder

1. `FLAT_V72_EXIT_REFINEMENT_V1` — no development pass.
2. `FLAT_V72_5M_SOFT_TIMING_RISK_V1` — no development pass.
3. `CAUSAL_SYMBOL_SECTOR_RANKING_V1` — no development pass.
4. `LONG_SHORT_REGIME_FAMILIES_V1` — no development pass.
5. `CAUSAL_CLEANSHOT_SMC_FEATURES_V1` — no development pass.

All stages used closed candles, strict chronological out-of-sample folds, pooled profit factor, the same `research_500` portfolio profile, fixed costs, and no manual symbol cherry-picking. No external holdout was opened because no candidate passed the development gate.

## Final SMC family result

The strongest candidate was `SMC_POI_VC_CHAIN`:

- valid folds: 10
- positive folds: 5/10
- trades: 47
- pooled PF: 1.2023
- average fold return: +0.067%
- worst fold return: -1.99%
- worst drawdown: 3.97%
- development gate: `WATCH_DEVELOPMENT`, not `PASS_DEVELOPMENT_SCREEN`

It failed the preregistered pass requirements because it had fewer than 60 trades and fewer than 6 positive folds. Directional diagnostics were also asymmetric:

- LONG: 20 trades, PF 0.5817, net PnL -9.529237
- SHORT: 27 trades, PF 2.0195, net PnL +17.637786

`SMC_IDM_BOS_CHAIN` had PF 1.3414 but only 29 trades and 3 positive folds, so it was also blocked as too sparse and unstable.

## Binding decision

- No candidate is frozen for holdout.
- The untouched external holdout remains unopened.
- No coefficients, thresholds, variants, symbol exclusions, or additional filters may be added after viewing these development results.
- The tested ladder is exhausted without a robust edge under the preregistered criteria.
- VPS, paper promotion, and live trading remain prohibited.

The negative result does not prove that every possible SMC strategy is impossible. It proves that the exact preregistered families tested in this ladder did not meet the required robustness standard and must not be promoted or rescued through post-hoc tuning on the same development period.
