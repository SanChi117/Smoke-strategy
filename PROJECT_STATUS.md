# Smoke Strategy Lab — Current Project Status

This repository is not a live trading bot yet.

It is currently a **research engine** for building and validating a crypto trading strategy before any real-money deployment.

## Current truth

The project has working research parts, but it is not yet a complete executable trading system.

Implemented:

```text
1. Normalized trade CSV format
2. Synthetic sample trade generator
3. Rolling Symbol Strength selector
4. Trade Quality Score layer
5. Structure Learning layer
6. Full Strategy Assembly comparison
7. GitHub Actions workflows for research reports
8. Compact CSV reports in results/
```

Not implemented yet:

```text
1. Real market data loader
2. Real strategy entry generator from candles
3. Real coin universe classification
4. Walk-forward validation
5. Out-of-sample holdout
6. Portfolio-level money management
7. Research server API
8. Live execution layer
9. Production monitoring
```

## Important conclusion from current tests

Testing isolated parts is not enough.

The current full assembly test showed:

```text
FULL_STRICT filters too hard.
FULL_BALANCED works better on the sample dataset.
```

Current sample result:

```text
ROLLING_TOP5:  +151.32% return, PF 1.9312, DD 3.89%, 984 executed trades
FULL_STRICT:   +67.92% return,  PF 2.7243, DD 4.56%, 271 executed trades
FULL_BALANCED: +166.64% return, PF 2.0672, DD 3.84%, 970 executed trades
```

This means the current direction should not be:

```text
all layers must say TAKE
```

The better current direction is:

```text
Rolling selector = universe filter
Quality + Structure = anti-trash gates
Avoid SKIP
Do not require TAKE from every layer
```

## What is missing for a real strategy

A real strategy must include the full chain:

```text
market data
→ feature builder
→ setup/entry generator
→ SL/TP/risk model
→ coin universe selector
→ quality/structure gates
→ portfolio simulator
→ walk-forward validation
→ reporting
→ optional research server
→ only later live execution
```

Right now the repository starts from ready-made trade CSVs. That is useful for testing filters, but it is not enough to prove a complete strategy.

## Server question

Yes, the project can be turned into a standalone research server.

But the correct first server is **not a live trading server**.

The correct next server should be:

```text
Research API server
```

It should expose endpoints like:

```text
/health
/run/sample-assembly
/run/real-assembly
/reports/latest
/universe/ranking
```

The server should run backtests and reports only. No orders. No API keys. No live execution.

## Current strategic uncertainty

The strategy is not proven universal yet.

Current evidence says:

```text
The logic benefits from selecting the right symbols.
A wide random universe dilutes the edge.
The strategy should not trade all coins equally.
```

So the likely correct answer is:

```text
The logic should be universal at the framework level,
but the coin universe must be selected and ranked for this strategy.
```

Universal framework does not mean every coin is tradable.

## Next required build phase

The next phase is not live trading.

The next phase is to build the missing executable research pipeline:

```text
1. Market data loader
2. Feature builder
3. Setup generator
4. Coin universe classifier
5. Portfolio/money management profiles
6. Walk-forward validation
7. Research server wrapper
```

Only after that we can say whether the strategy is universal, semi-universal, or only works on a specific coin class.
