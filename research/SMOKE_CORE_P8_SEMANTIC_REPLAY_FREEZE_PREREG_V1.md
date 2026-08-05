# SMOKE CORE 1.0 — P8 Exact Semantic Replay and Freeze Preregistration v1

## Identity

- Candidate: `SMOKE_CORE_1_0_CANDIDATE_1`
- P7 recognition: `SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1`
- P7 authoritative head: `b749be2578251a3b447a78a79009ff3d45cffc57`
- P7 authoritative run: `30899050584`
- P7 report artifact digest: `sha256:5eb666109dc3b5938062622f693e3dc0c6007ae09c252b36ccb9440ddf3a74e1`
- P7 independent ENTRY_READY: `2620`

## P8 gate A — exact semantic replay

P8 must replay the frozen P1–P7 semantics without tuning or outcome access. The authoritative causal path and the execution-optimized path must consume the same closed-candle inputs and produce canonicalized decision records with identical:

- symbol, direction, family, fold and timestamp;
- lifecycle and decision;
- scenario fingerprint and rearm lineage;
- POI, liquidity, interaction, structure, target and protected-swing provenance;
- economics/risk admission state;
- counted/excluded status under global fingerprint de-duplication.

Canonical comparison excludes only transport metadata that cannot alter a decision. Exact gate: `mismatch_count = 0`.

## P8 gate B — semantic freeze

After gate A passes:

1. Record the exact Git commit SHA and SHA-256 digests of all P1–P8 semantic source files, tests and workflow.
2. Verify that the frozen P7 recognition contract is unchanged: period, source, universe, directions, folds, weights, thresholds, lifecycle, evidence anti-double-counting, fingerprint, rearm and no-outcome scope.
3. Emit a no-outcome freeze manifest and rerun regression CI.
4. Freeze PASS requires replay mismatch count zero, complete manifest coverage and green P1–P8 regression CI.

## Prohibitions

Before P8 freeze PASS:

- no profitability, PnL, future return, trade outcome, TP/SL result, MFE/MAE, PF, drawdown or equity fields;
- no threshold, score, family, lifecycle, fingerprint or rearm changes;
- no paper, live, VPS or real-order execution.

## Next gate

Only after P8 freeze PASS may a separate development-profitability preregistration be committed. That later one-shot test must use the unchanged portfolio/risk/cost rules, stop-first ambiguity, at least 60 trades, pooled PF >= 1.20, average trade return after all costs > 0, at least 6/10 positive folds and max drawdown <= 8%. A failure closes Candidate 1 without tuning.