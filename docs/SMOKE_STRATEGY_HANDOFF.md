# Smoke Strategy — Project Handoff

This document is the current recovery/handoff point for the Smoke Strategy project.
It exists so the project can be resumed safely if a ChatGPT conversation becomes unavailable.

## Current project purpose

Smoke Strategy is a **research-only trading strategy lab**.

It is not a live trading bot.
It does not open orders.
It does not close orders.
It does not use private Binance account data.
It does not require Binance API keys for the current research flow.

Current research flow:

```text
real Binance public candles
-> candle feature generation
-> candidate setup generation
-> risk plans
-> generated trades
-> integrated portfolio simulation
-> paper-mode reports
-> report sanity checks
-> matrix comparison
-> baseline candidate
-> walk-forward validation
-> research decision gate
-> downloadable GitHub Actions artifact
```

## Repository

```text
SanChi117/Smoke-strategy
```

## Current status

The CI smoke workflow has been expanded and has been reported green after the following layers were added:

- public Binance candle loader
- Binance Vision fallback for GitHub-hosted runner geo blocks
- one-command real Binance research runner
- research report diagnosis analyzer
- real-data parameter matrix runner
- baseline candidate promotion from matrix output
- walk-forward validation runner
- research decision gate
- CI artifact upload for research outputs
- deep research suite runner
- manual deep research mode in GitHub Actions

## Important safety constraints

The project must remain research-only unless explicitly changed later.

Current constraints:

```text
No API keys required
No private account endpoints
No order endpoints
No live trading
No execution layer
No account balance/position reading
Public OHLCV only
```

## Key scripts added or updated

### Public Binance candle loader

```text
scripts/load_binance_candles.py
strategy_lab/binance_market_data.py
strategy_lab/binance_market_data_smoke_test.py
```

Purpose:

- download public Binance candles
- write project-compatible candles CSV
- use Binance Futures endpoint first
- fallback to Binance Vision spot endpoint when Futures endpoint returns HTTP 451 on GitHub runners

Typical command:

```bash
python scripts/load_binance_candles.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
  --interval 1h \
  --limit 1000 \
  --out data/binance_real_candles.csv
```

### One-command real Binance research runner

```text
scripts/run_binance_real_research.py
```

Purpose:

- download public candles
- run end-to-end pipeline
- write research diagnosis

Command:

```bash
python scripts/run_binance_real_research.py
```

Main output:

```text
results/binance_real/research_diagnosis.md
results/binance_real/end_to_end_summary.csv
results/binance_real/report_sanity_summary.csv
results/binance_real/candle_research_report.csv
```

### Research report diagnosis analyzer

```text
scripts/analyze_research_reports.py
```

Purpose:

- read report files
- produce a compact diagnosis
- flag sparse tests, over-filtering, poor PF, negative avg R, sanity failures, paper blocks, etc.

Typical output:

```text
research_diagnosis.md
```

### Real-data matrix runner

```text
scripts/run_binance_real_matrix.py
```

Purpose:

- download/reuse real candles
- compare multiple strategy configurations
- create matrix summary
- create baseline candidate files

Compared configs currently include:

```text
BASE_T5_C40
MORE_COINS_T8_C40
MORE_COINS_T10_C35
SOFTER_GATES_T8_C35
STRICT_T5_C50
```

Main command:

```bash
python scripts/run_binance_real_matrix.py
```

Main outputs:

```text
results/binance_real_matrix/matrix_summary.csv
results/binance_real_matrix/matrix_summary.md
results/binance_real_matrix/baseline_candidate/baseline_candidate.json
results/binance_real_matrix/baseline_candidate/baseline_candidate.md
```

Important fix already made:

`run_end_to_end_pipeline` now accepts `PipelineConfig`, and the matrix runner now passes the per-config values into the actual pipeline. This means matrix rows now really apply:

```text
rolling_top_n
quality_take_threshold
quality_watch_threshold
structure_take_threshold
structure_watch_threshold
min_confidence
```

### Baseline candidate promotion

```text
scripts/promote_matrix_baseline.py
```

Purpose:

- read matrix_summary.csv
- choose the highest score row
- write baseline_candidate.json and baseline_candidate.md

This is a research candidate only, not live approval.

### Walk-forward validation

```text
scripts/run_binance_walk_forward.py
```

Purpose:

- validate the baseline candidate across chronological folds
- include warmup/lookback before each validation window
- run end-to-end pipeline per fold
- produce walk-forward summary

Command:

```bash
python scripts/run_binance_walk_forward.py
```

Expanded command:

```bash
python scripts/run_binance_walk_forward.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,TONUSDT \
  --interval 1h \
  --limit 1500 \
  --windows 3 \
  --lookback-days 30
```

Main outputs:

```text
results/binance_walk_forward/walk_forward_summary.csv
results/binance_walk_forward/walk_forward_summary.md
```

Possible verdicts:

```text
PASS_WALK_FORWARD_REVIEW
WATCH_TOO_SPARSE
WATCH_UNSTABLE
BLOCK_NO_VALID_FOLDS
```

### Research decision gate

```text
scripts/make_research_decision.py
```

Purpose:

- read matrix summary
- read baseline candidate
- read walk-forward summary
- write final research decision

Main outputs:

```text
results/research_decision/research_decision.md
results/research_decision/research_decision.json
```

Possible decisions:

```text
PROMOTE_TO_DEEPER_RESEARCH
WATCH_EXPAND_SAMPLE
WATCH_TUNE_STRATEGY
WATCH_SANITY_REVIEW
WATCH_RISK_REVIEW
BLOCK_NO_MATRIX
BLOCK_NO_VALID_WFO
BLOCK_SANITY_FAIL
```

### Deep research suite

```text
scripts/run_deep_research_suite.py
```

Purpose:

- run the full research suite outside the quick CI checks
- larger universe
- deeper matrix
- walk-forward validation
- final research decision

Command:

```bash
python scripts/run_deep_research_suite.py
```

Default deep universe:

```text
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT,
DOGEUSDT, ADAUSDT, LINKUSDT, AVAXUSDT, TONUSDT,
NEARUSDT, APTUSDT, ARBUSDT, OPUSDT, INJUSDT
```

Default settings:

```text
interval = 1h
limit = 1500 candles per symbol
walk-forward windows = 4
lookback-days = 30
profile = growth_100_20x
```

Main outputs:

```text
results/deep_research/matrix/
results/deep_research/walk_forward/
results/deep_research/decision/research_decision.md
results/deep_research/decision/research_decision.json
```

## GitHub Actions workflow

Workflow file:

```text
.github/workflows/smoke.yml
```

The workflow currently runs:

```text
rolling smoke test
integrated pipeline smoke test
candle pipeline smoke test
data quality CLI smoke test
Binance market data smoke test
Binance real-data quick research check
Binance real-data matrix quick check
Binance walk-forward quick check
research decision gate
artifact upload
report sanity CLI smoke test
universe input smoke test
paper mode smoke test
regime samples smoke test
local demo smoke test
```

Artifact name:

```text
smoke-binance-research-results
```

Artifact includes:

```text
data/binance_real_ci_candles.csv
results/binance_real_ci/**
results/binance_real_matrix_ci/**
results/binance_walk_forward_ci/**
results/research_decision_ci/**
results/deep_research_manual/**
```

## Manual deep research through GitHub Actions

The workflow has a manual input:

```text
run_deep_research = true / false
```

Manual UI path:

```text
GitHub -> repository -> Actions -> Smoke Test -> Run workflow -> run_deep_research=true
```

This runs:

```bash
python scripts/run_deep_research_suite.py \
  --root results/deep_research_manual \
  --interval 1h \
  --limit 1500 \
  --windows 4 \
  --lookback-days 30
```

Main manual deep output in artifact:

```text
results/deep_research_manual/decision/research_decision.md
```

## Important note about automatic deep run

At the time this handoff was written, direct UI dispatch was not available through the assistant's GitHub tools. A safe attempt to add commit-message-triggered deep research was blocked by the tool safety layer, so the project was not changed in that direction.

Current reliable options:

1. Run deep research locally with:

```bash
python scripts/run_deep_research_suite.py
```

2. Run it manually in GitHub Actions with `run_deep_research=true`.

The assistant can still modify code, inspect CI failures, and analyze artifacts/logs after a run.

## What to do next

Recommended next project step:

```text
Run the deep research suite and inspect results/deep_research_manual/decision/research_decision.md
```

Then proceed based on the decision:

```text
PROMOTE_TO_DEEPER_RESEARCH -> run larger/paper-mode review
WATCH_EXPAND_SAMPLE -> increase symbols/history
WATCH_TUNE_STRATEGY -> inspect weak setup/regime groups and tune filters/exits
WATCH_SANITY_REVIEW -> fix report sanity issues
WATCH_RISK_REVIEW -> reduce risk or tighten filters
BLOCK_* -> fix pipeline/data before continuing
```

## Recovery note for future chats

If this chat is unavailable, open a new chat and say:

```text
Continue Smoke Strategy from docs/SMOKE_STRATEGY_HANDOFF.md in SanChi117/Smoke-strategy.
Use GitHub as source of truth. The current state is research-only: real Binance public data -> matrix -> baseline -> walk-forward -> decision gate -> artifact. Do not add live trading or API keys.
```
