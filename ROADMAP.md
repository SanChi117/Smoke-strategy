# Smoke Strategy Lab — Roadmap

Research mode only.

No live trading. No exchange keys. No order execution.

## Current baseline

The project currently has a working research chain:

```text
synthetic or user candles
→ data quality validation
→ universe input validation/filtering
→ feature builder
→ setup generator
→ risk model
→ candle exit simulator
→ generated trades
→ integrated pipeline
→ portfolio simulation
→ report sanity checks
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
data quality validation
report sanity checks
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
deterministic regime samples
regime batch comparison
walk-forward research skeleton
compact walk-forward report
walk-forward parameter grid skeleton
universe input validation
universe-filtered end-to-end runner
VPS research skeleton
GitHub smoke checks
```

Next:

```text
real market data adapter
real universe feed
server hardening
paper mode skeleton
```

Exit criteria:

```text
all smoke checks green
local demo works with one command
server reports are readable
pipeline never silently produces empty outputs
walk_forward_report.csv exists and is readable
parameter_grid_report.csv exists and is readable
universe_input_report.csv explains missing/usable symbols
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

Already started:

```text
scripts/check_candles_quality.py
data_quality_summary.csv
data_quality_report.csv
data_quality_issues.csv
scripts/check_universe_input.py
universe_input_summary.csv
universe_input_report.csv
filtered_candles.csv
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
can filter candles by universe.csv
candle_research_report.csv is produced
pipeline_summary.csv is produced
walk_forward_report.csv is produced
parameter_grid_report.csv is produced
reports identify weak/strong symbols
```

## Phase 3 — Walk-forward optimization

Goal: avoid tuning the strategy only on one fixed sample.

Already implemented:

```text
rolling walk-forward windows
walk_forward_windows.csv
walk_forward_summary.csv
walk_forward_report.csv
stability_score
best/worst window tracking
parameter_grid_summary.csv
parameter_grid_report.csv
min_confidence grid skeleton
```

Next planned:

```text
train/test window splitting
parameter grid for RR / stop settings
setup-family performance comparison
regime performance comparison
out-of-sample report
best-parameter stability report
```

Main questions:

```text
Which setup types survive out-of-sample?
Which coins should be ignored by the strategy itself?
Does risk_grade actually predict better outcomes?
Does the rolling selector improve or over-filter?
Do parameters remain stable across multiple windows?
```

Exit criteria:

```text
walk-forward report exists
best parameters are not chosen from one window only
strategy remains stable across multiple periods
parameter optimization does not overfit one regime
```

## Phase 4 — Real universe feed

Goal: let the system evaluate many symbols but trade only those that fit the current strategy logic.

Already implemented:

```text
universe input list
requested vs available symbol report
minimum history filter
missing symbol report
filtered_candles.csv
universe-filtered strategy runner
```

Next planned:

```text
real exchange/public universe source
liquidity filters
minimum volume filters
symbol quality ranking
exclude weak/dirty markets automatically
```

Design rule:

```text
The user may provide many symbols.
The system filters the universe before research.
The strategy decides which generated trades pass quality/risk gates.
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
report_sanity_summary.csv
candle_research_report.csv
candle_exit_diagnostics.csv
pipeline_risk_diagnostics.csv
pipeline_decisions.csv
regime_batch_summary.csv
walk_forward_report.csv
parameter_grid_report.csv
universe_input_report.csv
```

Exit criteria:

```text
setup types have distinct behavior
bad setup families are filtered or downgraded
risk grades correlate with better outcomes
strategy does not depend on one symbol or one regime
walk-forward stability improves, not just one-window performance
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
parameter grid validation
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
1. Real market data adapter
2. Real universe feed
3. Server hardening
4. Paper mode
5. Strategy improvement by reports
6. Live layer decision gate
```

## Hard safety rules

```text
No exchange keys in repository.
No live orders in research server.
No public server without auth.
No strategy changes without smoke checks.
No live layer until paper mode and WFO are done.
```
