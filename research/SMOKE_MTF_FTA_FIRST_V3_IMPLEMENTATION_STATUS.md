# SMOKE MTF FTA-FIRST V3 — Implementation Status

Status: `CORE_IMPLEMENTED_CI_PENDING`

Branch: `agent/smoke-mtf-fta-first-v3`

## Completed

- Separate V3 branch created from the frozen V2 research infrastructure.
- One candidate preregistered before implementation.
- External 4H/1D/1W/1M FTA is selected before route acceptance.
- Active HTF POI is required.
- Allowed routes remain fresh H1 raid or H1 VC plus later closed 15m test.
- Causal 5m BOS is required after route confirmation.
- A later closed 15m pullback to the broken BOS pivot is required.
- Entry is the next aligned 15m open.
- Stop priority is post-BOS 5m swing, post-BOS 15m swing, then pullback wick.
- The preselected external FTA is never moved to manufacture RR.
- RR 1.70 and quality 55 remain fixed.
- Regression tests cover external FTA filtering, post-BOS pullback, post-BOS stop priority and structural RR.

## Not yet completed

- First CI result.
- Outcome-blind full-period recognition runner.
- Semantic replay and accelerated-runtime equivalence.
- Independent ENTRY_READY count across the five preregistered symbols.
- Recognition freeze.

Profitability, holdout, VPS, paper and live remain prohibited.
