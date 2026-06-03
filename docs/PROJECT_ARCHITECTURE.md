# Project Architecture

Smoke Strategy Lab must be built as a layered research project, not as scattered scripts.

## Layer 0 — Data

Purpose:

```text
Load candles and normalized trades.
```

Planned modules:

```text
strategy_lab/data_loader.py
strategy_lab/candle_store.py
strategy_lab/trade_schema.py
```

Inputs:

```text
OHLCV candles
existing backtest trades
manual CSV exports
```

Outputs:

```text
normalized candles
normalized trade rows
```

Current status:

```text
Partial. Trade CSV format exists. Candle loader does not exist yet.
```

## Layer 1 — Feature Builder

Purpose:

```text
Convert candles into market features.
```

Features should include:

```text
trend regime
range regime
volatility regime
liquidity / volume state
structure state
risk bucket
session bucket
```

Planned module:

```text
strategy_lab/feature_builder.py
```

Current status:

```text
Missing. Some structure fallbacks exist only for sample tests.
```

## Layer 2 — Setup Generator

Purpose:

```text
Generate candidate trades from market features.
```

Setups:

```text
breakout
pullback
range rotation
trend continuation
countertrend reaction
ignition
```

Planned module:

```text
strategy_lab/setup_generator.py
```

Current status:

```text
Missing. The repo currently starts from ready-made trades.
```

## Layer 3 — Risk Model

Purpose:

```text
Calculate entry, stop, target, risk distance, target realism, and position limits.
```

Planned module:

```text
strategy_lab/risk_model.py
```

Must support:

```text
fixed risk profile
small-balance profile
leverage constraints
max positions
max margin load
symbol concentration limits
countertrend target compression
trend target extension
```

Current status:

```text
Partial. Capital simulation exists. Full money management profiles do not exist yet.
```

## Layer 4 — Coin Universe Selector

Purpose:

```text
Decide which coins are suitable for the current strategy.
```

This is mandatory because wide random universes diluted edge in previous tests.

Planned module:

```text
strategy_lab/universe_selector.py
```

Coin classes:

```text
trend-friendly
range-friendly
volatile-but-clean
chaotic / avoid
low-liquidity / avoid
```

Current status:

```text
Partial. Rolling Symbol Strength exists, but real coin classification does not exist yet.
```

## Layer 5 — Strategy Gates

Purpose:

```text
Filter candidate trades using quality and structure layers.
```

Existing modules:

```text
strategy_lab/rolling_symbol_strength.py
strategy_lab/trade_quality_score.py
strategy_lab/structure_learning.py
strategy_lab/strategy_assembly.py
```

Current result:

```text
Full strict gate over-filters.
Balanced gate works better on sample.
```

Current preferred model:

```text
Rolling Top-N universe
+ reject quality SKIP
+ reject structure SKIP
+ do not require TAKE from both layers
```

## Layer 6 — Portfolio Simulator

Purpose:

```text
Run realistic portfolio tests.
```

Must include:

```text
capital
risk per trade
leverage
fees
slippage
max positions
max margin
reinvestment ON/OFF
drawdown
loss streak
symbol concentration
```

Current status:

```text
Partial. simulate_capital exists, but profile system is missing.
```

## Layer 7 — Validation

Purpose:

```text
Prove whether the strategy survives outside the fitted sample.
```

Required tests:

```text
train/test split
walk-forward optimization
out-of-sample holdout
bull/bear/flat market slices
long/short breakdown
per-symbol breakdown
universe stability
```

Current status:

```text
Missing.
```

## Layer 8 — Research Server

Purpose:

```text
Run reports from a standalone server or VPS without live trading.
```

Planned module:

```text
strategy_lab/server.py
```

Endpoints:

```text
GET  /health
POST /run/sample-assembly
POST /run/real-assembly
GET  /reports/latest
GET  /universe/ranking
```

Current status:

```text
Missing.
```

## Layer 9 — Live Execution

Purpose:

```text
Only after research validation, optionally connect to live alerts/execution.
```

Current status:

```text
Not planned for the current phase.
```

## Current architectural conclusion

The project must move from:

```text
script collection
```

to:

```text
research platform
```

The next real build step should be the missing executable research pipeline, not live trading.
