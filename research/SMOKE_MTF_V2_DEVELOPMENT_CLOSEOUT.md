# SMOKE MTF V2 — Development Closeout

Status: `FAILED_DEVELOPMENT_GATE_CLOSED`

## Frozen candidate

- Recognition freeze SHA: `492eee9fdba5993b7f518e9a1ff38576e8b14285`
- Development trigger SHA: `bc041a388a3123a88acdb1cb62256f6297e678ce`
- Workflow run: `29906237656`
- Result artifact: `smoke-mtf-v2-development-profitability-v2-result`
- Artifact id: `8555252922`
- Artifact digest: `sha256:3ff8f1fb6c0052d326cfe9d3c6e61d520587cedf61e5c24e1e2657ea09f220fc`

## Preregistered result

- Development period: `2025-01-01` through `2026-07-01`
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, AAVEUSDT
- Chronological folds: 10
- Accepted trades: 1
- Pooled PF: 0.00
- Average net trade return: -1.3093%
- Positive folds: 0/10
- Portfolio net return: -0.5417%
- Maximum drawdown: 0.5417%
- Funding coverage: PASS
- Final verdict: FAIL

## Decision

This frozen V2 candidate is closed. It did not satisfy the preregistered minimum trade-count, pooled PF, positive-average-return, or positive-fold gates. The drawdown gate alone passed.

The failed candidate must not be tuned against observed PnL, TP/SL outcomes, MFE/MAE, or individual trade results. No external holdout, VPS, paper, or live deployment is allowed for V2.

## Allowed next step

Run a separate no-PnL funnel audit over the already exposed development period. The audit may inspect only causal recognition-state counts, transition rates, route counts, rejection reasons, pre-outcome structural RR geometry, and timing/coverage. It may not inspect future returns or trade outcomes.

After the no-PnL audit, preregister at most one materially new V3 candidate, validate its semantics, freeze it, and run one development screen under the same governance.
