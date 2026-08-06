# SMOKE CORE Candidate 1 — Development Profitability Transport Amendment V1

## Причина

Authoritative development-profitability workflow PR #15 обнаружил, что часть исходных symbol-fold shards превышает жёсткий лимит GitHub-hosted runner в 360 минут. Это вычислительный timeout, а не результат profitability gate и не изменение frozen Candidate 1.

## Изменение транспорта

Исходные 200 логических shards сохраняются:

- 5 symbols;
- 10 chronological folds;
- 4 logical shards на каждый symbol-fold.

Каждый логический shard выполняется двумя непрерывными физическими половинами. Workflow использует 400 physical subshards с `shard_count=8`, затем восемь частей объединяются обратно в тот же исходный symbol-fold partition до global fingerprint deduplication и outcome aggregation.

## Неизменяемые правила

Не меняются:

- exact frozen P1–P8 Candidate 1 semantics;
- dataset, период, universe, directions и 10 folds;
- causal candle visibility;
- entry, stop, target, costs, funding, risk и portfolio rules;
- stop-first same-bar ambiguity;
- global fingerprint deduplication;
- единственный authoritative development test;
- frozen gates: >=60 closed trades, PF >=1.20, positive average net trade return, >=6/10 positive folds, max drawdown <=8%.

Это amendment только вычислительного транспорта, созданный после runner timeout и до появления authoritative profitability report.

<!-- Technical retrigger for the existing authoritative PR workflow only; no semantic, gate, dataset, or transport change. -->
<!-- 2026-08-07 synchronization retrigger only; authoritative contract and implementation unchanged. -->
