# SMOKE Strategy — полный исторический пересмотр гипотез

Дата начала повторного аудита: 2026-07-16

Режим: research only. Live, VPS execution и реальные ордера заблокированы.

## 1. Зачем нужен повторный аудит

Проект SMOKE прошёл несколько архитектурных линий: Cleanshot/Smart Money, Pine Flat, Selective Feature Engineering, Rolling Symbol Strength, sector rotation, micro-context filters, MTF 1D/4H/15M, HYBRID v2 и последующие causal-исправления.

Часть идей была отброшена не после строгого независимого теста, а по одной из причин:

- сменился фокус проекта;
- GitHub workflow падал после расчёта;
- использовалась синтетическая или неполная выборка;
- результаты считались до исправления lookahead;
- использовались незакрытые HTF-свечи;
- warm-up попадал в OOS-результат;
- идея проверялась только как жёсткий фильтр, хотя могла работать как score или sizing factor;
- фиксированный core или конкретный режим рынка создавал скрытую подгонку;
- выборка была слишком маленькой.

Поэтому старый статус «отклонено» больше не считается окончательным без повторной causal-проверки.

## 2. Неприкосновенные правила нового исследования

Все повторные тесты обязаны соблюдать:

1. Только закрытые 15M/4H/1D свечи.
2. Никакого результата незакрытой сделки в Quality, Structure, Symbol Strength или ranking.
3. Warm-up используется только для обучения и не входит в OOS PnL.
4. Одновременные кандидаты ранжируются по известным на входе данным, а не по алфавиту.
5. Комиссии, проскальзывание и портфельные лимиты одинаковы между A/B.
6. PF считается по общему пулу прибыли и убытков, а не как среднее PF фолдов.
7. Development и external holdout разделены.
8. На holdout запускается только один заранее замороженный кандидат.
9. Нельзя выбирать отдельные удачные монеты или периоды после просмотра результата.
10. Любая идея должна сравниваться с простым контрольным baseline.

## 3. Реестр исторических торговых гипотез

### H01. Rolling Symbol Strength

История: первое ядро нового репозитория. Идея — выбирать сильные символы по завершённым прошлым сделкам с lookback/rebalance/top-N.

Почему была отложена:

- ранние лучшие результаты были на синтетических сделках;
- старая symbol-strength диагностика могла давать PF=99 и 100% win rate;
- позже tactical candidates обходили rolling gate;
- causal lookahead был исправлен уже после основной линии исследования.

Новый статус: **ОБЯЗАТЕЛЬНО ПОВТОРНО ТЕСТИРОВАТЬ**.

Новые варианты:

- rolling как жёсткий gate;
- rolling только как ranking bonus;
- rolling как risk multiplier;
- lookback 30/60/90 дней;
- rebalance 7/14/30 дней;
- top-N 5/8/12;
- отдельные LONG и SHORT рейтинги.

### H02. Sector Rotation / Dynamic Active Universe

История: рынок делился на сектора, строился sector ranking, затем выбирались сильные монеты внутри активных секторов.

Почему была отложена:

- проект перешёл к full tagged universe, где sector tags использовались в основном для отчёта;
- ранний sector cycle не прошёл полный современный causal pipeline;
- часть workflow была инфраструктурно хрупкой.

Новый статус: **ОБЯЗАТЕЛЬНО ПОВТОРНО ТЕСТИРОВАТЬ**.

Новые варианты:

- сектор только как ranking feature;
- sector momentum + symbol strength;
- отдельный sector breadth;
- запрет сектора только после достаточной собственной статистики;
- сравнение fixed core / full universe / dynamic sectors.

### H03. Fixed Core против Dynamic Universe

История: фиксированный core INJ/TON/DOGE/ARB/NEAR/OP давал сильные результаты, но мог быть cherry-picked. При расширении u8 → u20 → u40/u80 edge размывался.

Новый статус: **ПОВТОРНО ТЕСТИРОВАТЬ КАК КОНТРОЛЬ**, но fixed core не может стать production baseline без независимой проверки.

Тест:

- fixed historical core;
- liquidity-based fixed universe;
- dynamic rolling universe;
- dynamic sector universe;
- полный tagged universe.

### H04. Режимный Pullback

История: пользователь предлагал включать pullback только в подходящем трендовом режиме, а не считать его постоянным setup.

Почему идея не была реализована полноценно:

- старый pullback фактически определялся положением в диапазоне;
- поздний pullback_resumption стал слишком редким;
- режим включения не был отдельной моделью.

Новый статус: **ВЫСШИЙ ПРИОРИТЕТ**.

Новый режим должен проверять до входа:

- устойчивость тренда;
- степень перегрева;
- глубину и длительность отката;
- сохранность структуры;
- возвращение импульса;
- HTF alignment;
- volatility fit.

Pullback mode должен быть feature/state, а не постоянным allowlist setup.

### H05. Trend / Countertrend Target Compression

История: пользователь предлагал держать широкую цель по тренду и сокращать TP на контртрендовом отскоке.

Почему отложено: pipeline долго использовал почти единую target policy.

Новый статус: **ВЫСШИЙ ПРИОРИТЕТ**.

Тестовые target policies:

- trend aligned: 1.75R / 2.0R / structure target;
- countertrend: 0.8R / 1.0R / nearest liquidity;
- neutral regime: no trade или reduced target;
- volatility-normalized target;
- time-stop отдельно для trend и countertrend.

### H06. Связующая метрика качества Setup Quality / Trade Confidence

История: пользователь заметил, что фильтры могут душить друг друга и нужна не ещё одна кнопка BLOCK, а единая метрика точности.

Текущая система имеет отдельные Quality и Structure, но они долго работали как независимые gates и иногда нерелевантная global history блокировала новый setup.

Новый статус: **ВЫСШИЙ ПРИОРИТЕТ**.

Новая модель должна объединять только причинные признаки:

- context alignment;
- structure quality;
- symbol/sector strength;
- volatility fit;
- pullback maturity;
- entry confirmation;
- target realism;
- liquidity state.

Проверить три применения score:

- ranking при одновременных сигналах;
- risk sizing;
- gate только после достаточной sample history.

### H07. 5M Confirmation как мягкий признак

История: обязательный 5M gate был отклонён из-за TOO_FEW_EXECUTED.

Проблема старого решения: проверялся в основном вариант «блокировать без 5M», но не полноценно проверялись ranking/risk/entry-delay применения.

Новый статус: **ПОВТОРНО ТЕСТИРОВАТЬ, НО НЕ КАК ОБЯЗАТЕЛЬНЫЙ GATE**.

Варианты:

- 5M confirmation даёт score bonus;
- уменьшает риск при отсутствии подтверждения;
- выбирает лучший из одновременных 15M кандидатов;
- допускает entry delay на 1 закрытую 5M свечу;
- логируется в shadow без блокировки.

### H08. LONG и SHORT как разные стратегии

История: рынок по-разному вознаграждает LONG и SHORT. Последние тесты показали, что одинаковые правила нестабильны между периодами.

Новый статус: **ВЫСШИЙ ПРИОРИТЕТ**.

Правило: общий сервер и risk framework, но отдельные:

- setup definitions;
- context requirements;
- candle filters;
- target policies;
- cooldown;
- Quality/Structure histories;
- symbol rankings.

### H09. Flat v7.2 / Range Mean Reversion

История: отдельная Pine-линия LONG от нижней границы Donchian с запретом центра, шириной диапазона, динамическим volume threshold, structural SL и swing TP.

Почему была отброшена: проект переключился на Python/MTF research, а не потому что Flat была строго опровергнута современным causal WFO.

Новый статус: **ПОВТОРНО РЕАЛИЗОВАТЬ КАК ОТДЕЛЬНУЮ STRATEGY FAMILY**.

Нельзя смешивать Flat с trend pullback в одном baseline до отдельной оценки.

Обязательный A/B:

- Flat v7.2 faithful port;
- без 60M trend filter;
- dynamic volume on/off;
- structural TP против fixed RR;
- range-regime gate.

### H10. Cleanshot / Smart Money Features

История: FVG, order blocks, fractals, liquidity sweeps, RSI divergence, volume profile, 4H/1D context.

Почему отложено: архитектура Telegram/AI стала слишком тяжёлой, а сама feature family не была полностью опровергнута.

Новый статус: **ПОВТОРНО РАССМОТРЕТЬ ТОЛЬКО КАК ПРОЗРАЧНЫЕ FEATURES**, не как субъективные рисунки и не как AI-решение.

Приоритетные формализуемые признаки:

- liquidity sweep + reclaim;
- displacement candle;
- FVG size/fill state;
- fractal break/retest;
- distance to HTF imbalance;
- volume expansion;
- premium/discount location.

RSI divergence и volume profile тестировать позже, только после базовых causal features.

### H11. Liquidity / Micro-context Filters

История: low_sweep_reclaim, none, bear_rejection, volume ratio, high volatility block и direction context давали сильные результаты на fixed core.

Почему статус сомнительный:

- часть результатов была до causal hardening;
- metadata join сначала был ошибочен;
- fixed core мог создать selection bias.

Новый статус: **ПОВТОРНО ТЕСТИРОВАТЬ НА DYNAMIC UNIVERSE**.

### H12. Breakout / Ignition / Watch Impulse / Range Rotation

История: эти setup types последовательно блокировались после слабых результатов, но часто их общая история затем влияла на другие setup types.

Новый статус:

- breakout: **ПОВТОРНЫЙ ОТДЕЛЬНЫЙ ТЕСТ**, только после squeeze/expansion regime;
- ignition: **ПОВТОРНЫЙ ОТДЕЛЬНЫЙ ТЕСТ**, с continuation confirmation;
- watch_impulse: **НЕ ТОРГОВАТЬ**, но использовать как feature/state;
- range_rotation: **СРАВНИТЬ С FLAT**, не смешивать с trend family.

### H13. BTC/ETH Market Context

История: BTC/ETH сначала использовались как корреляционный фон, затем роль уменьшилась.

Новый статус: **ПОВТОРНО ТЕСТИРОВАТЬ КАК MARKET-REGIME FEATURE**.

Не блокировать альт только из-за простой корреляции. Проверять:

- BTC/ETH trend breadth;
- realized volatility;
- dominance proxy только при доступной воспроизводимой истории;
- alt/BTC relative strength;
- risk-on/risk-off state.

### H14. Symbol Personality / Type Layer

История: пользователь предлагал определять тип и силу монеты, потому что broad universe размывал edge.

Новый статус: **ПОВТОРНО ТЕСТИРОВАТЬ**.

Причинные признаки:

- median volatility;
- wickiness;
- trend persistence;
- breakout follow-through;
- pullback depth distribution;
- liquidity/turnover proxy;
- stop distance stability.

Тип символа не должен вычисляться по будущим сделкам OOS.

### H15. Sniper / Strong-Move Potential

История: пользователь хотел отличать обычный вход от снайперского и забирать движения 4–6%+, которые старая стратегия часто пропускала.

Новый статус: **ИССЛЕДОВАТЬ ПОСЛЕ СТАБИЛЬНОГО BASELINE**.

Сначала нужен label, известный только после сделки для обучения, но causal feature set на входе:

- compression before expansion;
- HTF space to target;
- volume expansion;
- relative strength;
- clean liquidity path;
- low opposing structure density.

Нельзя использовать strong-move label как входной признак.

## 4. Идеи, которые не являются торговым edge

Эти компоненты можно возвращать только после стратегии, но не нужно повторно backtest-ить как гипотезы:

- Telegram bot;
- AI explanation/filter without fixed reproducible features;
- TradingView → VPS → 3Commas bridge;
- live Binance execution;
- charts/control panel;
- Google Drive backup;
- multiple-project UI.

Они относятся к доставке, управлению и инфраструктуре, а не к качеству входа.

## 5. Порядок повторного исследования

### Phase A — восстановление и честные контрольные baseline

1. Faithful current MTF control.
2. Rolling Symbol Strength: gate / rank / risk.
3. Dynamic sectors: rank / risk.
4. Separate LONG and SHORT histories.
5. Trend/countertrend target policies.

### Phase B — режимные стратегии

6. Regime-aware pullback family.
7. Flat v7.2 family.
8. Breakout/ignition family отдельно.

### Phase C — дополнительные признаки

9. 5M soft confirmation.
10. Cleanshot causal features.
11. BTC/ETH market context.
12. Symbol personality.

### Phase D — единый decision layer

13. Composite setup quality score.
14. Candidate ranking.
15. Risk sizing by confidence.
16. Portfolio simulation.

## 6. Критерии прохождения

Development candidate:

- минимум 8 временных фолдов;
- pooled PF >= 1.20;
- минимум 5/8 положительных фолдов;
- worst fold > -2.5%;
- DD <= 8%;
- желательно 60+ сделок;
- ни одна сторона или одна монета не создаёт почти всю прибыль.

External holdout:

- один замороженный кандидат;
- PF > 1.10 минимум, целевой >= 1.20;
- средняя доходность > 0;
- минимум половина фолдов положительные;
- DD <= 8%;
- LONG/SHORT оцениваются отдельно;
- при малой выборке статус WATCH, не PASS.

Paper promotion:

- только после положительного external holdout;
- минимум 100 закрытых paper-сделок;
- минимум 30 календарных дней;
- daily DD stop 2%;
- weekly DD stop 5%;
- max 3 consecutive stops;
- max 1 position per symbol.

## 7. Первый пакет повторных тестов

Первым запускается не очередной узкий SHORT-filter, а исторический пакет:

1. Current MTF control.
2. Rolling rank only.
3. Rolling risk only.
4. Sector rank only.
5. Rolling + sector rank.
6. Separate LONG/SHORT target compression.
7. Regime pullback state.
8. 5M soft score only.

Flat и Cleanshot запускаются вторым отдельным пакетом, чтобы разные strategy families не загрязняли друг другу статистику.

## 8. Текущий вывод

Предыдущий HYBRID/MTF baseline и последние SHORT refinements не должны считаться центром проекта. Они становятся лишь одной контрольной веткой.

Главная новая цель SMOKE:

> Найти устойчивую комбинацию режима рынка, strategy family, symbol/sector selection, target policy и causal quality ranking, которая проходит development и внешний holdout без подглядывания и ручного cherry-pick.
