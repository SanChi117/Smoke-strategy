# SMOKE CORE Candidate 1 — Development Profitability Preregistration v1

## Identity and immutable basis

- Test ID: `SMOKE_CORE_CANDIDATE_1_DEVELOPMENT_PROFITABILITY_FIXED_V1`.
- Candidate: `SMOKE_CORE_1_0_CANDIDATE_1`.
- Frozen P8 head: `eef6bf319f53e4434d5f99bf54bc7f78c1b41f75`.
- Authoritative P8 workflow: `31004476021`.
- P8 artifact: `p8-semantic-replay-freeze-v1`, digest `sha256:89a497b9a3dbe79ece05440bd56a365dda410b324c41399420c89aab22b8ec3b`.
- Freeze manifest SHA-256: `8fa00da7f22c70ddd48208a3cdcf678d540f29738bbff6ef9978f72477e4b429`.
- Frozen recognition count: exactly `2620` independent counted `ENTRY_READY` rows.

This preregistration is committed before reading any development return, target/stop outcome, profit factor, average return, fold profitability, or drawdown.

## Fixed development dataset and candidate stream

- Binance Vision USD-M Futures monthly klines, 5m.
- Inclusive period: `2024-01-01T00:00:00+00:00` through `2024-06-30T23:55:00+00:00`.
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, AAVEUSDT.
- Directions: LONG and SHORT.
- Exactly 10 chronological folds.
- Exact P7/P8 causal semantics, decision thresholds, evidence anti-double-counting, lifecycle, fingerprint/rearm and global dedupe are immutable.
- The profitability adapter captures entry, structural stop and frozen target only at the existing `_build_observation` boundary. It may not create, delete or reclassify recognized setups.

## Fixed execution and outcome rules

- Outcome bars are closed 5m bars from the entry 15m bar onward.
- If stop and target are both touched on the same 5m bar, stop is applied first.
- A position exits at the first stop or target touch.
- A position unresolved at the end of the fixed development period exits at the final development 5m close.
- All costs use the frozen P5 `CostModel`: entry fee 0.04%, exit fee 0.04%, entry slippage 0.02%, exit slippage 0.02%, expected funding 0.01%, cost buffer 0.02%.
- Risk uses the frozen P5 `RiskLimits`: 0.5% equity risk per position, 2% total open risk, isolated margin, 20x default leverage, 25x maximum leverage, 10% maximum margin per position, 25% total margin and 2.5x total notional.
- Simultaneous candidates are ordered deterministically by frozen upstream score, net geometry RR and fingerprint. No outcome value participates in admission or ranking.
- Fold attribution uses the entry fold.

## Preregistered gates

Candidate 1 passes development profitability only if all conditions hold:

1. at least 60 admitted closed trades;
2. pooled profit factor >= 1.20;
3. average trade return after all costs > 0;
4. at least 6 of 10 folds have positive net PnL;
5. maximum portfolio drawdown <= 8%.

## One-test rule and decisions

Exactly one valid development profitability test is authorized. A run that fails before producing a complete verified report is a technical invalid run, not a second economic test, and may only be repaired for syntax/import/API/workflow/data/artifact defects or a contract-confirmed bug.

- PASS: prepare an untouched external holdout preregistration; do not run holdout automatically in this package.
- FAIL: close Candidate 1 without tuning and without a second development profitability run.
- Paper, live, VPS and real orders remain prohibited.
