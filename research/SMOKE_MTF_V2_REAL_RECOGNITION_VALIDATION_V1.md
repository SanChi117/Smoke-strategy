# SMOKE MTF V2 — Real Recognition Validation V1

## Verdict

**COMPUTATIONAL PASS / SEMANTIC REVIEW REQUIRED**

The frozen no-outcome run completed successfully on all five symbols, the aggregate passed, and the combined artifact passed the outcome-field exclusion contract. The recognition core is **not frozen yet** because no snapshot reached `ENTRY_READY` and the completed BOS cases require chart-level semantic verification.

Profitability development, external holdout, VPS, paper and live remain blocked.

## Frozen run

- Workflow run: `29727847823`
- Trigger SHA: `834aee3e03c3e86dc361765eeb8e10e76ffb5459`
- Combined artifact: `8455210237`
- Artifact digest: `sha256:b0ff8ec4e846130a8ffe51bcdaafb68e3de1c2b08aeff26e9507b087a55fbd20`
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, AAVEUSDT
- History: 2024-07-01 through 2025-02-08
- Recognition scan: 2025-02-01 through 2025-02-08
- Selection: first 4 chronologically per `symbol/side/setup_state`
- PnL, future returns, TP/SL outcomes, MFE and MAE: excluded

## Computational result

- Closed 15m bars: **3,360**
- Side snapshots: **6,720**
- `NO_CONTEXT`: **5,472**
- `POI_TESTED`: **993**
- `WAIT_5M_BOS`: **251**
- `M5_BOS_CONFIRMED`: **4**
- `ENTRY_READY`: **0**
- Frozen review rows: **87**
- Unique structural fingerprints: **28**
- Repeated selected rows: **59**
- Combined no-outcome contract: **PASS**

Reason counts overlap and are diagnostic, not mutually exclusive:

- no confirmed 5m BOS: **6,498**
- POI without closed H1 raid or VC: **4,928**
- H1 VC zone not yet tested on a closed 15m candle: **437**
- quality below frozen minimum: **595**
- context blocked by transition/range/opposite direction: frequent and expected by the hard context gate

## Per-symbol states

| Symbol | 15m bars | Side snapshots | NO_CONTEXT | POI_TESTED | WAIT_5M_BOS | M5_BOS | ENTRY_READY | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AAVEUSDT | 672 | 1,344 | 1,152 | 156 | 34 | 2 | 0 | 6:58 |
| BTCUSDT | 672 | 1,344 | 800 | 430 | 113 | 1 | 0 | 7:53 |
| ETHUSDT | 672 | 1,344 | 1,344 | 0 | 0 | 0 | 0 | 7:26 |
| LINKUSDT | 672 | 1,344 | 992 | 250 | 101 | 1 | 0 | 9:12 |
| SOLUSDT | 672 | 1,344 | 1,184 | 157 | 3 | 0 | 0 | 7:17 |

## Four completed 5m BOS chains

| Time | Symbol | Side | Route | POI TF | Entry | Stop | Target | Target TF/source | RR | Result |
|---|---|---|---|---|---:|---:|---:|---|---:|---|
| 2025-02-03 03:15 | AAVEUSDT | LONG | fresh H1 raid | 1D | 225.40 | 202.5254 | 230.30 | 1H bear FVG | 0.2142 | blocked |
| 2025-02-03 06:00 | AAVEUSDT | LONG | fresh H1 raid | 1H | 230.19 | 202.3567 | 230.30 | 1H bear FVG | 0.0040 | blocked |
| 2025-02-03 06:00 | LINKUSDT | LONG | fresh H1 raid | 4H | 18.181 | 16.0610 | 18.1987 | 1H high pivot | 0.0084 | blocked |
| 2025-02-05 18:15 | BTCUSDT | SHORT | fresh H1 raid | 4H | 96,832.2 | 98,985.96 | 96,823.6 | 1H bull FVG | 0.0040 | blocked |

All four were correctly rejected by the frozen `RR >= 1.70` rule. This is not a profitability result. The chart review must determine whether:

1. the raided H1 liquidity was identified correctly;
2. the 5m body-close BOS was structurally valid;
3. the stop belongs behind the correct swept structural extreme;
4. the selected 1H FTA is the correct target under the source-model rules.

## Semantic findings

1. **No `ENTRY_READY` case.** The run proves the pipeline executes causally, but it does not yet validate a full trade-ready chain.
2. **Only the raid path completed BOS.** VC-path examples reached `WAIT_5M_BOS`; no selected VC example completed the chain in this frozen week.
3. **Completed chains had extremely poor structural space.** RR ranged from 0.003952 to 0.214212. The system blocked them; the stop/target geometry requires visual verification.
4. **ETH stayed `NO_CONTEXT` for the entire week.** This may be correct for a RANGE/TRANSITION week or may reveal an overly broad conflict rule. It must be checked without future outcome data.
5. **87 rows represent 28 structural cases.** Persistent states produced repeated chronological rows. Fingerprints expose repetition without changing or deleting the frozen sample.
6. **`qualifying_snapshots = 6,720` is not setup frequency.** The exporter currently calls any snapshot with a POI “qualifying”; this metric is diagnostic only.

## Required next step

Recognition remains open for semantic validation:

1. Review all four `M5_BOS_CONFIRMED` cases.
2. Review the five unique `WAIT_5M_BOS` structural fingerprints.
3. Review representative `NO_CONTEXT` cases for every symbol, with emphasis on ETHUSDT.
4. Correct definitions only where a mismatch with the documented Drive rules is demonstrated.
5. Re-run the same recognition contract after technical/semantic corrections.
6. Freeze the recognition core explicitly before preregistering any profitability development screen.

No threshold may be changed because of future profit or loss.
