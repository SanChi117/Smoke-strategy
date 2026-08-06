# SMOKE CORE P9 — Transport Amendment V1

## Причина

Первый полный P9 matrix run подтвердил, что часть preregistered geometry jobs превышает жёсткий лимит GitHub-hosted runner в 360 минут. Ошибка относится только к вычислительному транспорту: preregistration, frozen P7/P8 authority chain, P1–P9 regression и успешно завершённые shards не выявили semantic mismatch.

## Разрешённое техническое изменение

Исходная preregistration фиксирует 200 логических geometry shards:

- 5 symbols;
- 10 chronological folds;
- 4 contiguous logical shards на symbol-fold.

Каждый из 200 логических shards теперь выполняется как две непрерывные физические половины. Таким образом CI использует 400 physical subshards, после чего каждая соседняя пара концептуально восстанавливает исходную логическую границу, а все восемь физических частей собираются в тот же исходный symbol-fold partition до global fingerprint parity и outcome evaluation.

## Что не меняется

Не изменяются:

- Candidate 1 и frozen P1–P8 semantics;
- dataset, период, universe и 10 folds;
- порядок candle visibility и causal history;
- entry, stop, target и P5/P6 objects;
- global fingerprint deduplication;
- expected exact fingerprint set из 2620 ENTRY_READY;
- fill, slippage, fees, funding, STOP_FIRST и 48h horizon;
- risk, portfolio admission и ranking;
- profitability metrics и preregistered PASS/FAIL thresholds.

## Научная граница

Это transport-only amendment, созданный после обнаружения runner timeout и до появления полного P9 outcome report. Он не разрешает изменение параметров по результатам доходности и не превращает development sample в holdout.
