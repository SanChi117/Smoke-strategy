# Parameter Grid and Universe Input

Research mode only.

No live trading. No exchange keys. No order execution.

## 1. Walk-forward parameter grid

The parameter grid runner tests multiple `min_confidence` values through walk-forward windows.

Run:

```bash
python scripts/run_parameter_grid.py \
  --candles data/candles.csv \
  --out-dir results/parameter_grid \
  --min-confidence-values 30,40,50 \
  --window-days 30 \
  --step-days 15
```

Main outputs:

```text
results/parameter_grid/parameter_grid_summary.csv
results/parameter_grid/parameter_grid_report.csv
```

Use `parameter_grid_report.csv` first.

Important metrics:

```text
best_param_name
best_param_value
best_stability_score
best_avg_ret_pct
best_executed_windows
avg_stability_score
pass_rows
watch_rows
fail_rows
```

This is not final optimization yet. It is the first skeleton for comparing parameter stability across WFO windows.

## 2. Universe input validation

The universe input checker lets you provide a broad symbol list while the system checks which symbols are actually usable in the candle dataset.

Universe CSV format:

```text
symbol
BTCUSDT
ETHUSDT
SOLUSDT
```

Run:

```bash
python scripts/check_universe_input.py \
  --candles data/candles.csv \
  --universe data/universe.csv \
  --out-dir results/universe_input \
  --min-candles 100
```

Main outputs:

```text
results/universe_input/universe_input_summary.csv
results/universe_input/universe_input_report.csv
results/universe_input/filtered_candles.csv
```

Statuses:

```text
OK       symbol requested and has enough candles
WARN     symbol exists but has too little history
MISSING  symbol requested but not found in candles
EXTRA    symbol exists in candles but was not requested
```

## 3. Universe-filtered end-to-end run

After validating the requested universe, the runner can automatically create `filtered_candles.csv` and run the strategy only on usable symbols.

Run:

```bash
python scripts/run_universe_end_to_end.py \
  --candles data/candles.csv \
  --universe data/universe.csv \
  --out-dir results/universe_end_to_end \
  --profile growth_100_20x \
  --min-confidence 40 \
  --min-candles 100
```

Main outputs:

```text
results/universe_end_to_end/universe_input/universe_input_summary.csv
results/universe_end_to_end/universe_input/universe_input_report.csv
results/universe_end_to_end/universe_input/filtered_candles.csv
results/universe_end_to_end/strategy/end_to_end_summary.csv
results/universe_end_to_end/strategy/report_sanity_summary.csv
```

Design rule:

```text
The user may provide many symbols.
The system filters the universe before strategy research.
The strategy still decides which generated trades pass quality/risk gates.
```
