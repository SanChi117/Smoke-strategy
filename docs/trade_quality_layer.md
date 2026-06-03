# Trade Quality Score layer

Research-only adaptive scoring layer for Smoke-strategy.

It does not open trades and does not change strategy code automatically. It only scores completed runner trades and writes CSV reports.

Default candidate:

```text
lookback_days = 30
min_history_trades = 3
take_threshold = 65
watch_threshold = 50
```

Input CSV:

```text
data/real_runner_trades.csv
```

Required columns:

```text
symbol,side,entry_time,entry,stop,r_mult
```

Recommended columns:

```text
exit_time,exit,kind,source,trend_context,volatility_regime,setup_type
```

Output:

```text
results/trade_quality_scored_trades.csv
results/trade_quality_breakdown.csv
results/trade_quality_summary.csv
```

Run:

```bash
python scripts/run_trade_quality_report.py --input data/real_runner_trades.csv
```

Temporary sample run:

```bash
python scripts/generate_sample_runner_trades.py --out data/sample_runner_trades.csv
python scripts/run_trade_quality_report.py --input data/sample_runner_trades.csv
```
