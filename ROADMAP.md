# Smoke Strategy Lab — Roadmap

Research mode only.

No live trading. No exchange keys. No order execution.

## Current baseline

The project currently has a working research chain:

```text
synthetic or user candles
→ feature builder
→ setup generator
→ risk model
→ candle exit simulator
→ generated trades
→ integrated pipeline
→ portfolio simulation
→ diagnostics/reports
```

The default research risk profile is:

```text
profile: growth_100_20x
balance: $100
leverage: 20x
base risk: 0.75%
max risk: 1.00%
max positions: 2
```

## Phase 1 — Research core hardening

Status: active.

Goal: make the local research platform stable before connecting real market data.

Done:

```text
market data CSV layer
feature builder
setup generator
setup-aware risk model
candle exit simulator
exit diagnostics
compact candle research report
integrated pipeline
portfolio simulator
risk diagnostics
research server
local demo
VPS research skeleton
GitHub smoke checks
```

Next:

```text
add real candle CSV adapter format checks
add stronger validation of candle gaps / duplicate candles / symbol coverage
add report sanity rules for too few trades / too many time-stops / weak avg R
add deterministic sample datasets for trend/range/high-vol regimes
```

Exit criteria:

```text
all smoke checks green
local demo works with one command
server reports are readable
pipeline never silently produces empty outputs
```

## Phase 2 — Real market data loader

Goal: load real historical OHLCV data without adding live execution.

Planned:

```text
exchange-neutral OHLCV CSV loader
symbol universe input file
data quality report
missing candle detection
duplicate candle detection
minimum history check
per-symbol coverage report
```

Important:

```text
read-only public market data first
no private account API
no order endpoints
no exchange keys in repo
```

Exit criteria:

```text
can run end-to-end on real candles.csv
candle_research_report.csv is produced
pipeline_summary.csv is produced
reports identify weak/strong symbols
```

## Phase 3 — Walk-forward optimization

Goal: avoid tuning the strategy only on one fixed sample.

Planned:

```text
train/test window splitting
rolling walk-forward runs
parameter grid for min_confidence / RR / stop settings
setup-family performance comparison
regime performance comparison
out-of-sample report
```

Main questions:

```text
Which setup types survive out-of-sample?
Which coins should be ignored by the strategy itself?
Does risk_grade actually predict better outcomes?
Does the rolling selector improve or over-filter?
```

Exit criteria:

```text
walk-forward report exists
best parameters are not chosen from one window only
strategy remains stable across multiple periods
```

## Phase 4 — Real universe feed

Goal: let the system evaluate many symbols but trade only those that fit the current strategy logic.

Planned:

```text
universe input list
liquidity filters
minimum volume filters
minimum history filters
symbol quality ranking
exclude weak/dirty markets automatically
```

Design rule:

```text
The user may provide many symbols.
The strategy decides which ones are currently tradable.
```

Exit criteria:

```text
universe ranking is meaningful
weak coins are blocked automatically
high-quality symbols remain eligible
reports explain why symbols were blocked
```

## Phase 5 — Server hardening

Goal: make research server safer and more production-like before any live layer.

Planned:

```text
request auth token
run id tracking
latest run metadata
per-run report folders
better error responses
health and diagnostics endpoints
log rotation docs
systemd deployment validation
```

Not allowed yet:

```text
public unauthenticated server
exchange keys
order execution
3Commas execution
TradingView live webhooks
```

Exit criteria:

```text
server can be deployed to VPS in research mode
all endpoints are protected or local-only
reports are stored per run
failed runs are easy to debug
```

## Phase 6 — Strategy improvement

Goal: improve the actual decision logic after the research plumbing is stable.

Planned:

```text
improve trend/range regime detection
add market session context
add BTC/ETH market regime context
add liquidity sweep refinements
add range-specific setup family
add trend-continuation setup family
add high-volatility restrictions
add setup-specific time-stop rules
```

Main reports to use:

```text
candle_research_report.csv
candle_exit_diagnostics.csv
pipeline_risk_diagnostics.csv
pipeline_decisions.csv
```

Exit criteria:

```text
setup types have distinct behavior
bad setup families are filtered or downgraded
risk grades correlate with better outcomes
strategy does not depend on one symbol or one regime
```

## Phase 7 — Pre-live paper mode

Goal: run the system on fresh market data without real orders.

Planned:

```text
scheduled data refresh
paper signal generation
paper trade tracking
paper reports
alert-only mode
manual review workflow
```

Still not allowed:

```text
automatic real orders
private account trading keys
unreviewed live webhooks
```

Exit criteria:

```text
paper mode runs for multiple weeks
signals and exits are tracked
reports remain stable
manual review confirms logic is understandable
```

## Phase 8 — Live layer decision gate

Live layer is not automatic.

Before live trading, the project must pass:

```text
real data validation
walk-forward validation
paper mode validation
server hardening
authentication
risk limits
kill switch
manual override
clear logging
```

Only after that should we discuss:

```text
TradingView webhooks
3Commas or exchange integration
order sizing
position tracking
live risk guardrails
```

## Current priority order

```text
1. Real candle CSV/data loader validation
2. Stronger report sanity checks
3. Deterministic regime sample datasets
4. Walk-forward optimization
5. Real universe feed
6. Server hardening
7. Paper mode
8. Live layer decision gate
```

## Hard safety rules

```text
No exchange keys in repository.
No live orders in research server.
No public server without auth.
No strategy changes without smoke checks.
No live layer until paper mode and WFO are done.
```
