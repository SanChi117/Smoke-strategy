# Full Strategy Assembly

This is the current full-stack research test for Smoke Strategy Lab.

It combines the layers that were previously tested separately:

```text
Rolling Symbol Strength
+ Trade Quality Score
+ Structure Learning
+ Capital Simulation
```

No live trading. No API keys. No 3Commas. No Telegram bot.

## Purpose

Separate layers can look good in isolation but still conflict when combined.

This report checks whether the layers:

```text
1. reinforce each other
2. over-filter and kill trade count
3. improve PF but reduce total return too much
4. create a better balanced candidate strategy
```

## Main scenarios

```text
ALL
ROLLING_TOP5
QUALITY_TAKE
STRUCTURE_TAKE
QUALITY_AND_STRUCTURE_TAKE
ROLLING_AND_QUALITY_TAKE
ROLLING_AND_STRUCTURE_TAKE
FULL_STRICT
FULL_BALANCED
FULL_QUALITY_GATE
FULL_STRUCTURE_GATE
FULL_NOT_SKIP
```

## Current sample result

Best practical assembly on the deterministic sample:

```text
FULL_BALANCED
```

Meaning:

```text
Rolling Top 5
+ quality decision is TAKE or WATCH
+ structure decision is TAKE or WATCH
```

Sample output:

```text
ROLLING_TOP5:    ret +151.32%, PF 1.9312, DD 3.89%, exec 984
FULL_STRICT:     ret +67.92%,  PF 2.7243, DD 4.56%, exec 271
FULL_BALANCED:   ret +166.64%, PF 2.0672, DD 3.84%, exec 970
```

## Interpretation

`FULL_STRICT` gives the cleanest trades but filters too much. It increases quality but lowers total return.

`FULL_BALANCED` keeps nearly the same trade count as rolling baseline, improves PF, improves final return, and does not increase drawdown on the sample test.

This suggests the current direction should not be a hard all-filters-must-be-TAKE model.

The better direction is:

```text
Rolling selector as the main universe filter.
Quality/structure layers as anti-trash gates.
Avoid SKIP.
Do not require TAKE from every layer.
```

## Required next validation

The result is still based on deterministic sample trades. It is not proof of real-market profitability.

Next required step:

```text
run the same assembly on data/real_runner_trades.csv
```

Only if the same pattern survives on real trades should this become the default research baseline.
