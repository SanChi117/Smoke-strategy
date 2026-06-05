# Smoke Strategy Lab

Research-only crypto strategy lab.

No Telegram bot. No 3Commas. No exchange API keys. No live trading.

The current project is a modular research platform for testing whether a wide crypto universe can be filtered into tradable setups by the strategy itself.

## Current research chain

```text
candles.csv
→ data quality validation
→ market features
→ candidate setups
→ risk plans
→ candle exit simulation
→ generated trades
→ universe / quality / structure gates
→ dynamic portfolio simulation
→ paper mode / review / decision
→ report sanity checks
→ reports
```

## Fastest start

```bash
python -m pip install --upgrade pip
pip install -e .
python scripts/run_local_demo.py
```

The demo creates synthetic candles and writes reports to:

```text
results/demo/
```

## First reports to read

```text
results/demo/report_sanity_summary.csv
results/demo/report_sanity_issues.csv
results/demo/paper/paper_decision_summary.csv
results/demo/paper/paper_review_summary.csv
results/demo/candle_research_report.csv
results/demo/candle_exit_diagnostics.csv
results/demo/generated_trades.csv
results/demo/pipeline_summary.csv
results/demo/pipeline_risk_diagnostics.csv
```

Use `report_sanity_summary.csv` first. It shows whether the generated research result is clean, suspicious, or failing basic sanity checks.

Then open `paper/paper_decision_summary.csv`. It gives a compact paper-mode decision:

```text
PASS
WATCH
BLOCK
```

Then open `candle_research_report.csv`. It gives the compact strategy view:

```text
winrate_pct
avg_r
total_r
best_setup_type
worst_setup_type
best_risk_grade
best_target_policy
best_symbol
worst_symbol
most_common_exit
```

## Report sanity checks

Sanity checks are created automatically after the end-to-end run:

```text
report_sanity_summary.csv
report_sanity_issues.csv
```

They flag suspicious results such as:

```text
data quality errors
too few generated_trades
too few executed_trades
weak candle avg_r
too many time-stop exits
weak walk-forward stability_score
missing report files
```

Check an existing reports folder without rerunning the strategy:

```bash
python scripts/check_report_sanity.py --out-dir results
```

Stricter example:

```bash
python scripts/check_report_sanity.py \
  --out-dir results \
  --min-generated-trades 10 \
  --min-executed-trades 2 \
  --min-candle-avg-r 0.0 \
  --max-time-stop-pct 50 \
  --min-wfo-stability-score 60
```

`WARN` does not mean the code failed. It means the result should be reviewed before trusting it.

## Paper mode

Paper mode is created automatically by the end-to-end pipeline.

Main files:

```text
paper/paper_signals.csv
paper/paper_journal.csv
paper/paper_positions.csv
paper/paper_review.csv
paper/paper_review_summary.csv
paper/paper_decision_summary.csv
paper/paper_summary.csv
```

Read first:

```text
paper/paper_decision_summary.csv
```

Decision values:

```text
PASS   basic paper review passed
WATCH  review needed before trusting the run
BLOCK  paper set failed basic review
```

Standalone paper mode:

```bash
python scripts/run_paper_mode.py \
  --generated-trades results/generated_trades.csv \
  --out-dir results/paper
```

Full documentation:

```text
docs/PAPER_MODE.md
```

## Compare market regimes

Generate deterministic trend/range/high-volatility samples:

```bash
python scripts/generate_regime_samples.py
```

Run all regimes through the full end-to-end pipeline:

```bash
python scripts/run_regime_batch.py
```

Main comparison file:

```text
results/regime_batch/regime_batch_summary.csv
```

Use it to compare:

```text
trend vs range vs high_vol vs mixed
generated_trades
executed_trades
ret_pct
max_dd_pct
candle_avg_r
best_setup_type
worst_setup_type
most_common_exit
```

Important: a weak or empty regime is information, not a code failure. It means the current setup/risk logic did not find enough valid opportunities in that market type.

## Walk-forward check

Run walk-forward windows on a candle dataset:

```bash
python scripts/run_walk_forward.py \
  --candles data/candles.csv \
  --out-dir results/walk_forward \
  --window-days 30 \
  --step-days 15 \
  --min-confidence 40
```

Main files:

```text
results/walk_forward/walk_forward_windows.csv
results/walk_forward/walk_forward_summary.csv
results/walk_forward/walk_forward_report.csv
```

Open `walk_forward_report.csv` first. It answers:

```text
How many windows passed?
How many windows were profitable or losing?
What was average ret_pct and max_dd_pct?
Which window was best/worst?
What is the stability_score and stability_status?
```

This is still a research skeleton. It does not optimize parameters yet; it checks whether the current logic survives multiple time windows.

## Run on your own candles

Input format:

```text
symbol,time,open,high,low,close,volume
```

Command:

```bash
python scripts/run_end_to_end_pipeline.py \
  --candles data/candles.csv \
  --out-dir results \
  --profile growth_100_20x \
  --min-confidence 40
```

Check candle quality only:

```bash
python scripts/check_candles_quality.py \
  --candles data/candles.csv \
  --out-dir results/data_quality \
  --min-candles 100 \
  --min-symbols 1
```

## Current risk profile

Default profile:

```text
growth_100_20x
balance: $100
leverage: 20x
base risk: 0.75%
max risk: 1.00%
max positions: 2
```

The simulator uses dynamic risk per trade:

```text
TAKE + TAKE = full risk
WATCH combinations = reduced risk
Any SKIP = blocked
```

## Research server

Start server locally:

```bash
python scripts/run_research_server.py \
  --host 127.0.0.1 \
  --port 8080 \
  --base-dir .
```

Health-check:

```bash
python scripts/health_check.py --host 127.0.0.1 --port 8080
```

Run end-to-end through server:

```bash
curl -X POST http://127.0.0.1:8080/run/end-to-end \
  -H 'Content-Type: application/json' \
  -d '{"candles_csv":"data/candles.csv","out_dir":"results","profile":"growth_100_20x","min_confidence":40}'
```

Run standalone paper mode through server:

```bash
curl -X POST http://127.0.0.1:8080/run/paper \
  -H 'Content-Type: application/json' \
  -d '{"generated_trades_csv":"results/runs/<run_id>/generated_trades.csv","out_dir":"results"}'
```

Read reports:

```bash
curl http://127.0.0.1:8080/reports/latest?out_dir=results
```

## Main modules

```text
strategy_lab/market_data.py
strategy_lab/data_quality.py
strategy_lab/feature_builder.py
strategy_lab/setup_generator.py
strategy_lab/risk_model.py
strategy_lab/candle_exit_simulator.py
strategy_lab/exit_diagnostics.py
strategy_lab/candle_research_report.py
strategy_lab/candle_pipeline.py
strategy_lab/report_sanity.py
strategy_lab/paper_mode.py
strategy_lab/paper_review.py
strategy_lab/end_to_end_pipeline.py
strategy_lab/walk_forward.py
strategy_lab/universe_selector.py
strategy_lab/portfolio_simulator.py
strategy_lab/risk_diagnostics.py
strategy_lab/research_server.py
```

## Smoke checks

Fast checks:

```bash
python -m strategy_lab.smoke_test
python -m strategy_lab.pipeline_smoke_test
python -m strategy_lab.candle_pipeline_smoke_test
python -m strategy_lab.data_quality_cli_smoke_test
python -m strategy_lab.report_sanity_cli_smoke_test
python -m strategy_lab.paper_mode_smoke_test
python -m strategy_lab.regime_samples_smoke_test
python -m strategy_lab.local_demo_smoke_test
```

Full/heavier checks also include:

```bash
python -m strategy_lab.end_to_end_smoke_test
python -m strategy_lab.walk_forward_smoke_test
python -m strategy_lab.research_server_smoke_test
python -m strategy_lab.regime_batch_smoke_test
```

## Docs

```text
QUICKSTART.md
ROADMAP.md
docs/PAPER_MODE.md
docs/PARAMETER_GRID_AND_UNIVERSE.md
docs/PROJECT_ARCHITECTURE.md
docs/UNIVERSE_AND_MONEY_MANAGEMENT.md
docs/TRADING_PLAYBOOK.md
docs/DEPLOY_RESEARCH_SERVER.md
PROJECT_STATUS.md
```

## Current status

Implemented:

```text
one-command local demo
market data CSV layer
data quality validation
report sanity checks
paper mode lifecycle
paper review and decision summary
regime sample generator
regime batch comparison
walk-forward research skeleton
compact walk-forward report
feature builder
setup generator
setup-aware risk model
candle exit simulator
exit diagnostics
compact candle research report
integrated pipeline
dynamic portfolio simulator
risk diagnostics
research server
VPS research deployment skeleton
GitHub smoke checks
```

Not implemented yet:

```text
real exchange market data loader
real live universe feed
walk-forward parameter optimization
production authentication
live alert/execution layer
```

## Safety rule

This repository stays research-only until validation proves the strategy is stable.

Do not add exchange API keys here yet.
