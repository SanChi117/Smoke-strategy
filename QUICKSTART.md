# Smoke Strategy Lab — Quickstart

Research mode only.

No live trading. No exchange keys. No order execution.

## 1. Install locally

```bash
python -m pip install --upgrade pip
pip install -e .
```

## 2. Run the one-command demo

```bash
python scripts/run_local_demo.py
```

The demo creates synthetic candles and runs the full research chain:

```text
synthetic candles
→ data quality validation
→ candle features
→ candidate setups
→ risk plans
→ candle exits
→ generated trades
→ integrated pipeline
→ report sanity checks
→ reports
```

Default output:

```text
data/demo_candles.csv
results/demo/
```

## 3. Main reports to open first

### 1. Report sanity

```text
results/demo/report_sanity_summary.csv
results/demo/report_sanity_issues.csv
```

Open this first.

It answers:

```text
Did the result pass basic sanity checks?
Are there data quality errors?
Were there too few generated/executed trades?
Is candle avg_r too weak?
Are there too many time-stop exits?
```

`WARN` does not mean the code failed. It means the result should be reviewed before trusting it.

### 2. Candle summary

```text
results/demo/candle_research_report.csv
```

Use this after sanity checks.

It answers:

```text
How many setups were generated?
What was winrate / avg R / total R?
Which setup type worked best/worst?
Which risk grade worked best?
What was the most common exit reason?
```

### 3. Exit breakdown

```text
results/demo/candle_exit_diagnostics.csv
```

Use this to inspect exits by:

```text
setup_type
risk_grade
target_policy
symbol
side
exit_reason
```

### 4. Generated trades

```text
results/demo/generated_trades.csv
```

This is the normalized trade CSV produced from candles.

It feeds the integrated pipeline.

### 5. Portfolio summary

```text
results/demo/pipeline_summary.csv
```

This shows the integrated portfolio result with the current risk profile:

```text
growth_100_20x
$100 balance
20x leverage
0.75% base risk
1.00% max risk
```

### 6. Risk diagnostics

```text
results/demo/pipeline_risk_diagnostics.csv
```

Use this to see why trades were allowed or blocked:

```text
not_in_current_rolling_top
quality_skip
structure_skip
allowed_full_balanced
```

## 4. Check existing reports only

Run sanity checks on an existing reports folder without rerunning the strategy:

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

Outputs:

```text
report_sanity_summary.csv
report_sanity_issues.csv
```

## 5. Compare market regimes

Generate deterministic trend/range/high-volatility samples:

```bash
python scripts/generate_regime_samples.py
```

Run all regimes through the full research chain:

```bash
python scripts/run_regime_batch.py
```

Main comparison file:

```text
results/regime_batch/regime_batch_summary.csv
```

Read it as a regime comparison table:

```text
trend      → trending synthetic market
range      → mean-reverting/range synthetic market
high_vol   → high-volatility synthetic market
mixed      → all regimes combined
```

Most important columns:

```text
generated_trades
executed_trades
ret_pct
max_dd_pct
candle_avg_r
candle_total_r
best_setup_type
worst_setup_type
most_common_exit
```

A weak or empty regime is useful information. It means the current logic did not find enough valid trades there.

## 6. Walk-forward check

Run rolling windows on your candle dataset:

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

Open this first:

```text
results/walk_forward/walk_forward_report.csv
```

It answers:

```text
How many windows completed successfully?
How many windows were profitable or losing?
What was average ret_pct and max_dd_pct?
Which window was best/worst?
What is the stability_score and stability_status?
```

Important metrics:

```text
windows_total
windows_ok
windows_error
profitable_windows
losing_windows
executed_windows
avg_ret_pct
avg_max_dd_pct
stability_score
stability_status
best_window
worst_window
```

This is not parameter optimization yet. It checks whether the current logic survives multiple time windows.

## 7. Run with custom output

```bash
python scripts/run_local_demo.py \
  --candles data/my_demo_candles.csv \
  --out-dir results/my_demo \
  --symbols 8 \
  --hours 1500 \
  --profile growth_100_20x \
  --min-confidence 40
```

## 8. Run candle pipeline on your own candles

Your CSV must contain:

```text
symbol,time,open,high,low,close,volume
```

Run:

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

## 9. Start research server

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

Or:

```bash
curl http://127.0.0.1:8080/health
```

## 10. Run through research server

### Run full candle-to-pipeline flow

```bash
curl -X POST http://127.0.0.1:8080/run/end-to-end \
  -H 'Content-Type: application/json' \
  -d '{"candles_csv":"data/candles.csv","out_dir":"results","profile":"growth_100_20x","min_confidence":40}'
```

### Read latest reports

```bash
curl http://127.0.0.1:8080/reports/latest?out_dir=results
```

## 11. Current project status

The current project is a research platform, not a live bot.

Implemented:

```text
market data CSV layer
data quality validation
report sanity checks
regime sample generator
regime batch comparison
walk-forward research skeleton
compact walk-forward report
feature builder
setup generator
risk model
candle exit simulator
exit diagnostics
candle research report
integrated pipeline
portfolio simulator
risk diagnostics
research server
local demo
GitHub smoke checks
```

Not live yet:

```text
real exchange data loader
real market universe feed
walk-forward parameter optimization
production authentication
live alert/execution layer
```

## 12. Safety rule

Do not add exchange API keys to this project yet.

The current phase is research, validation and architecture hardening.
