# Smoke Strategy Trading Playbook

Short operational documentation for research and future self-learning analysis.

This is not a live-trading instruction. It describes how the strategy should reason.

## Core idea

The strategy can receive a wide coin pool, even all available symbols, but it must not trade all of them.

The system must decide:

```text
which symbols are currently suitable
which setups are allowed
which trades are blocked
what risk profile to use
```

## Current default profile

```text
profile: growth_100_20x
balance: $100
leverage: 20x
base risk: 0.75% per trade
max risk: 1.00% only for strongest signals
max positions: 2
max margin load: 35%
reinvest: false in research phase
daily loss limit target: 3%
weekly loss limit target: 8%
```

## Decision model

A trade is allowed only when:

```text
symbol is not blocked by universe selector
trade is inside current rolling top selection
quality layer is not SKIP
structure layer is not SKIP
```

The system should not require all layers to say TAKE.

Preferred current logic:

```text
TAKE + TAKE = full confidence
TAKE + WATCH = allowed
WATCH + TAKE = allowed
WATCH + WATCH = allowed with reduced risk
Any SKIP = block
```

## Symbol logic

Symbols should be classified as:

```text
trend_friendly
volatile_clean
watch_only
chaotic_avoid
insufficient_history
```

Allowed by default:

```text
trend_friendly
volatile_clean
watch_only with reduced risk
```

Blocked by default:

```text
chaotic_avoid
insufficient_history
```

## Setup logic

Current strategic setup families:

```text
continuation
pullback
breakout
range_rotation
countertrend_reaction
ignition
```

Countertrend setups must not use wide targets by default.

Trend continuation and pullback can use wider targets only when quality and structure agree.

## Self-learning notes

The self-learning layer should record:

```text
symbol
side
setup_type
trend_context
volatility_regime
structure_type
quality_decision
structure_decision
risk_pct
result R
reason for allow/block
```

Future analysis should answer:

```text
Which symbols are improving?
Which symbols are degrading?
Which structure contexts work now?
Which setups should be disabled?
Is the strategy becoming too strict or too loose?
```

## Current research rule

Do not move to real money until the full pipeline works with:

```text
market data loader
feature builder
setup generator
risk model
universe selector
portfolio simulator
walk-forward validation
research server
```
