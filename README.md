# Smoke Strategy Lab

Clean isolated crypto strategy research repository.

This repo is separate from the old Telegram bot project. It is for strategy research only:

```text
trade CSV -> rolling symbol selection -> capital simulation -> report
```

No Telegram bot. No 3Commas. No API keys. No live trading.

## Current stage

```text
v2.4 Rolling Symbol Strength
```

Goal: check whether a wide universe can be stabilized by selecting only the strongest symbols using past data.

## Input CSV format

Required columns:

```text
symbol,side,entry_time,exit_time,entry,stop,exit,r_mult
```

Optional columns:

```text
kind,source
```

Example time format:

```text
2026-01-01T12:00:00
```

## Smoke test

```bash
python -m strategy_lab.smoke_test
```

Expected:

```text
SMOKE TEST OK
```

## Rolling symbol strength run

```bash
python -m strategy_lab.rolling_symbol_strength \
  --trades-csv data/trades.csv \
  --start 2026-01-01 \
  --end 2026-05-31 \
  --lookback-days 30 \
  --rebalance-days 7 \
  --top-n 8 \
  --initial-cash 500 \
  --risk-pct 0.02 \
  --leverage 20 \
  --max-positions 2
```

## Rules

1. First make the research core stable.
2. No live trading logic in this repository.
3. No secrets or API keys.
4. GitHub Actions only for smoke tests at first.
5. Real market-data adapters are added only after local smoke tests pass.
