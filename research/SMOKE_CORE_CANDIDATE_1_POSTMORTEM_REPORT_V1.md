# SMOKE CORE Candidate 1 — Post-Mortem Report V1

## Статус

Диагностический разбор завершён на точных authoritative artifacts единственного development profitability test Candidate 1.

Источник:
- run `31130707800`;
- test `SMOKE_CORE_CANDIDATE_1_DEVELOPMENT_PROFITABILITY_FIXED_V1`;
- frozen Candidate 1;
- 50 symbol-fold partitions;
- locked 5m dataset;
- 4053 уникальных observations;
- 2620 counted ENTRY_READY observations;
- 909 portfolio-accepted closed trades.

Диагностический replay воспроизвёл официальный результат до машинной точности:
- closed trades: `909`;
- pooled PF: `0.62430269896`;
- average trade return after costs: `-0.163690630394%`;
- max drawdown: `81.8723896881%`;
- ending equity: `2149.116500957`;
- outcomes: TARGET `150`, STOP `755`, FORCED_END `4`.

Этот документ не является вторым profitability test и не разрешает tuning Candidate 1.

## 1. Главный источник убытка — Liquidity Raid Reversal

### LIQUIDITY_RAID_REVERSAL
- trades: `765`;
- TARGET: `114`;
- STOP: `647`;
- target rate: `14.90%`;
- stop rate: `84.58%`;
- PF: `0.5408`;
- net PnL: `-8105.33`;
- average net move: `-0.3797%`.

### TREND_PULLBACK_CONTINUATION
- trades: `144`;
- TARGET: `36`;
- STOP: `108`;
- target rate: `25.00%`;
- stop rate: `75.00%`;
- PF: `1.0784`;
- net PnL: `+254.45`;
- average net move: `+0.1386%`.

Вывод: общий FAIL Candidate 1 в основном создаётся не всей recognition architecture, а family `LIQUIDITY_RAID_REVERSAL`. Trend Pullback выглядит существенно лучше, но это только exploratory observation на уже увиденном development dataset и не доказательство самостоятельного edge.

## 2. SHORT заметно хуже LONG

### LONG
- trades: `502`;
- PF: `0.7408`;
- net PnL: `-2954.15`;
- stop rate: `82.87%`.

### SHORT
- trades: `407`;
- PF: `0.4846`;
- net PnL: `-4896.73`;
- stop rate: `83.29%`.

Самый сильный exploratory family-direction slice:

### TREND_PULLBACK_CONTINUATION | LONG
- trades: `91`;
- TARGET: `24`;
- STOP: `67`;
- PF: `1.2869`;
- net PnL: `+576.20`;
- average net move: `+0.1818%`.

TREND_PULLBACK_CONTINUATION | SHORT остаётся отрицательным: PF `0.7399`, net PnL `-321.75`.

Вывод: симметричная LONG/SHORT логика не подтверждается. Candidate 2 не должен автоматически зеркалить одну и ту же гипотезу в обе стороны.

## 3. Самые разрушительные symbol-direction slices

По net PnL:
1. `LINKUSDT|LONG`: 122 trades, PF `0.3928`, net PnL `-1836.96`, stop rate `90.16%`;
2. `ETHUSDT|LONG`: 84 trades, PF `0.3738`, net PnL `-1296.90`;
3. `BTCUSDT|SHORT`: 55 trades, PF `0.2331`, net PnL `-1144.08`, stop rate `94.55%`;
4. `AAVEUSDT|SHORT`: 87 trades, PF `0.4475`, net PnL `-1028.73`;
5. `ETHUSDT|SHORT`: 74 trades, PF `0.4696`, net PnL `-951.99`.

Сильнейший exploratory slice:

### BTCUSDT | LONG
- trades: `69`;
- TARGET: `18`;
- STOP: `48`;
- FORCED_END: `3`;
- PF: `1.7431`;
- net PnL: `+1078.74`;
- average net move: `+0.4490%`.

Это не разрешение торговать только BTC LONG; это подсказка, что Candidate 2 должен моделировать context/direction asymmetry, а не считать все symbols и directions одинаковыми экземплярами одной логики.

## 4. Upstream score практически не отделяет хорошие сделки от плохих

- score `<70`: 668 trades, PF `0.6293`, net PnL `-5389.79`;
- `70–74.999`: 197 trades, PF `0.6254`, net PnL `-1876.43`;
- `75–79.999`: 43 trades, PF `0.4894`, net PnL `-689.33`;
- `80–84.999`: только 1 trade.

Вывод: текущий upstream score не является полезным monotonic quality discriminator внутри реально допущенных сделок. Простое повышение score threshold не имеет достаточного основания и запрещено как tuning Candidate 1.

Для Candidate 2 нужен новый quality model, где score связан с вероятностью реализации сценария, а не только с количеством/силой upstream evidence.

## 5. Главная геометрическая проблема: очень высокий nominal RR не реализуется

### Raw RR 2.00–2.499
- 67 trades;
- TARGET `33`, STOP `34`;
- target rate `49.25%`;
- PF `1.2241`;
- net PnL `+191.49`.

### Raw RR >=2.50
- 841 trades;
- TARGET `117`, STOP `720`, FORCED_END `4`;
- target rate `13.91%`;
- stop rate `85.61%`;
- PF `0.5992`;
- net PnL `-8027.67`;
- average target distance `5.53%` против average stop distance `1.02%`.

Вывод: Candidate 1 часто выбирает очень далёкую theoretical target liquidity, создавая красивый nominal RR, но вероятность достижения цели слишком низкая. Это один из главных архитектурных дефектов.

Нельзя превращать наблюдение `2.00–2.499` в новый threshold на том же dataset. Для Candidate 2 следует изменить сам принцип выбора target: target должен быть causally attainable в текущем regime/volatility/structure horizon, а не просто максимально выгодным по nominal RR.

## 6. Простое расширение или сужение stop проблему не исправит

Все stop-distance buckets отрицательны:
- `<0.50%`: PF `0.4797`, stop rate `90.41%`;
- `0.50–0.99%`: PF `0.6602`;
- `1.00–1.49%`: PF `0.6693`;
- `1.50–1.99%`: PF `0.5225`;
- `>=2.00%`: PF `0.5433`.

Вывод: причина FAIL не сводится к тому, что stop «слишком узкий». Механическое расширение stop не является обоснованным решением.

## 7. Большинство плохих сделок ломается очень быстро

По фактическому времени до исхода:
- `<=30m`: 76 trades, PF `0.0886`, stop rate `97.37%`;
- `31–120m`: 252 trades, PF `0.0979`, stop rate `96.43%`;
- `121–360m`: 261 trades, PF `0.2131`, stop rate `91.19%`;
- `361–1440m`: 237 trades, PF `2.0702`;
- `>1440m`: 83 trades, PF `2.0396`.

Это не live-usable фильтр: holding time известно только после входа. Но это сильный diagnostic signal: большое число ENTRY_READY на самом деле являются сценариями, которые рынок опровергает почти сразу.

Candidate 2 должен искать причинные признаки до входа, которые отличают "immediate invalidation" от сценариев, способных удержаться хотя бы несколько часов.

## 8. Провал устойчив во времени

Fold net PnL отрицателен в 9 из 10 folds. Единственный положительный fold — `9` (`+155.13`, PF `1.2681`). Fold `8` почти flat (`-25.61`, PF `0.9698`).

Это исключает объяснение вида «один плохой период испортил нормальную систему».

## Что Candidate 1 доказал полезного

Несмотря на FAIL profitability, инфраструктурные результаты сохраняют ценность:
- deterministic P1–P8 semantics;
- exact replay parity;
- no future leakage;
- global fingerprint dedupe;
- causal lifecycle;
- stable recognition transport;
- locked data contracts;
- realistic cost/risk/portfolio execution.

Провален конкретный trading hypothesis layer Candidate 1, а не весь SMOKE CORE research stack.

## Candidate 2 — разрешённые исследовательские гипотезы

Candidate 2 должен быть новой preregistered гипотезой. Рекомендуемые направления проектирования:

1. **Family separation.** Liquidity Raid Reversal и Trend Pullback не должны использовать общий admission philosophy. Для Raid требуется новая causal confirmation model; Trend может стать самостоятельной hypothesis family.

2. **Direction asymmetry.** LONG и SHORT проектируются отдельно. Никакого автоматического зеркалирования без causal justification.

3. **Attainable-target model.** Target определяется через достижимую структуру + regime + volatility horizon. Nominal RR не должен быть главным основанием выбора дальней цели.

4. **Early-failure prevention before entry.** Нужен pre-entry persistence/acceptance test: подтверждение, что sweep/reclaim/pullback действительно удерживается, а не только произошёл технический trigger.

5. **Quality score redesign.** Новый score обязан отражать вероятность реализации конкретного scenario path. Старый upstream score не переносится как главный admission rank без пересмотра.

6. **Context-dependent family enablement.** Candidate 2 должен иметь причинное понятие market regime, в котором конкретная family разрешена/запрещена. Это проектируется до просмотра нового evaluation outcome.

7. **No post-hoc symbol blacklist.** Нельзя просто исключить LINK/ETH/BTC SHORT потому, что они были плохими на этом dataset. Symbol differences используются как evidence того, что model context incomplete, а не как готовый blacklist.

## Следующий формальный шаг

Создать `Candidate 2 Research Specification` до нового profitability evaluation:
- определить новый hypothesis contract;
- определить family/direction state machines;
- определить attainable target rule;
- определить pre-entry persistence/acceptance evidence;
- определить новый score semantics;
- выбрать evaluation design, который не превращает уже увиденный Candidate 1 development dataset в повторный authoritative test;
- preregister gates до результатов.

Candidate 1 остаётся закрытым без tuning.