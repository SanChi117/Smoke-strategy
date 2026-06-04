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
→ candle features
→ candidate setups
→ risk plans
→ candle exits
→ generated trades
→ integrated pipeline
→ reports
```

Default output:

```text
data/demo_candles.csv
results/demo/
```

## 3. Main reports to open first

### 1. Candle summary

```text
results/demo/candle_research_report.csv
```

Use this first.

It answers:

```text
How many setups were generated?
What was winrate / avg R / total R?
Which setup type worked best/worst?
Which risk grade worked best?
What was the most common exit reason?
```

### 2. Exit breakdown

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

### 3. Generated trades

```text
results/demo/generated_trades.csv
```

This is the normalized trade CSV produced from candles.

It feeds the integrated pipeline.

### 4. Portfolio summary

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

### 5. Risk diagnostics

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

## 4. Run with custom output

```bash
python scripts/run_local_demo.py \
  --candles data/my_demo_candles.csv \
  --out-dir results/my_demo \
  --symbols 8 \
  --hours 1500 \
  --profile growth_100_20x \
  --min-confidence 40
```

## 5. Run candle pipeline on your own candles

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

## 6. Start research server

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

## 7. Run through research server

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

## 8. Current project status

The current project is a research platform, not a live bot.

Implemented:

```text
market data CSV layer
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
walk-forward optimization
production authentication
live alert/execution layer
```

## 9. Safety rule

Do not add exchange API keys to this project yet.

The current phase is research, validation and architecture hardening.
