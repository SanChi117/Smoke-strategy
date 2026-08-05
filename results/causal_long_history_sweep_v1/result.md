# Causal long-history sweep

Data source: **Binance USDT-M Futures only** (no Spot fallback).
WFO windows: **6**, warm-up: **30 days**.

## Candidates
- LONGHIST_PULLBACK_SHORT_CONTROL_V1: **WATCH_TOO_SPARSE**, folds=4/6, trades=18, avg_ret=0.1083%, PF=40.3284, DD=3.65%
- LONGHIST_RESUMPTION_BALANCED_V1: **WATCH_TOO_SPARSE**, folds=3/6, trades=6, avg_ret=0.3317%, PF=49.5, DD=1.45%
- LONGHIST_RESUMPTION_HTF_V1: **WATCH_TOO_SPARSE**, folds=3/6, trades=4, avg_ret=0.3783%, PF=49.5, DD=1.45%
- LONGHIST_RESUMPTION_VR09_V1: **WATCH_TOO_SPARSE**, folds=1/6, trades=2, avg_ret=0.0917%, PF=16.5, DD=1.44%
- LONGHIST_RESUMPTION_HTF_VR09_V1: **WATCH_TOO_SPARSE**, folds=1/6, trades=1, avg_ret=0.13%, PF=16.5, DD=1.42%
- LONGHIST_RESUMPTION_NEUTRAL_V1: **WATCH_TOO_SPARSE**, folds=1/6, trades=1, avg_ret=0.03%, PF=16.5, DD=1.43%

No candidate is promoted by this screening alone; the leader still requires separate deep validation.
