# Universe Selection and Money Management

This document fixes an important strategic point:

```text
A universal framework is not the same as a strategy that trades every coin.
```

## Current conclusion

The strategy should be built as a universal framework, but it needs a selected and ranked coin universe.

Current evidence from previous tests:

```text
small curated universe worked better
wide random universe diluted the edge
rolling top-N improved stability
full strict gates over-filtered
balanced gates worked better on sample
```

So the current answer is:

```text
The strategy should not blindly trade all coins.
It should classify coins and trade only the types that fit the current setup logic.
```

## Coin classes

The project should classify coins into groups.

### 1. Trend-friendly coins

Good for:

```text
breakout
pullback
continuation
ignition
```

Expected behavior:

```text
clean directional movement
reasonable liquidity
not too many random wicks
responds to trend filters
```

### 2. Range-friendly coins

Good for:

```text
flat/range rotation
mean reversion
boundary-to-mid trades
```

Expected behavior:

```text
stable ranges
repeatable support/resistance behavior
moderate volatility
```

### 3. Volatile but clean coins

Good for:

```text
short-term momentum
limited-size trades
special high-volatility mode
```

Risk:

```text
needs smaller position size
wider stop or stricter confirmation
```

### 4. Chaotic coins

Usually avoid.

Signs:

```text
random wicks
low structure persistence
bad stop behavior
poor PF by symbol
unstable spread/slippage
```

### 5. Low-liquidity coins

Avoid for the main strategy.

Reasons:

```text
slippage
fake volume
bad fills
unstable stop execution
```

## Universal logic vs selected universe

The strategy logic can be universal at the architecture level:

```text
detect regime
generate setup
score trade quality
score structure
simulate portfolio
```

But the tradable universe should be selected dynamically:

```text
only coins that currently fit the strategy
```

## Required universe selector

The project needs:

```text
strategy_lab/universe_selector.py
```

It should rank coins using:

```text
recent PF
recent avg R
winrate
trade count
max loss streak
volatility fit
trend/range behavior
long/short balance
liquidity proxy
stability across windows
```

Output:

```text
symbol
class
score
allowed_setups
risk_multiplier
reason
```

## Money management profiles

Real money cannot use one static risk rule for every balance.

Needed profiles:

### Research profile

```text
initial_cash = 500
risk_pct = 0.5%
reinvest = False
max_positions = 2
max_margin_pct = 20%
```

Used for stable research comparisons.

### Small live test profile

Not active yet.

Possible future parameters:

```text
risk_pct = 0.25% to 0.5%
max_positions = 1 or 2
leverage capped
no reinvest at first
strict daily loss limit
```

### Growth profile

Not active yet.

Only after stable validation.

Possible future parameters:

```text
risk_pct = 0.5% to 1.0%
max_positions = 2 or 3
controlled reinvest
weekly risk reset
```

### Aggressive profile

Not active now.

Only after real out-of-sample validation.

## Current decision

Do not move to real money.

Next required research tasks:

```text
1. Build universe selector.
2. Build money management profiles.
3. Test strategy assembly across coin classes.
4. Check if the edge survives outside selected symbols.
5. Decide if the strategy is universal, semi-universal, or coin-class-specific.
```
