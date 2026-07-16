# SMOKE Strategy — полный ретроспективный аудит идей

Дата начала повторного аудита: 2026-07-16  
Режим: research only; live, testnet и реальные ордера запрещены.

## 1. Зачем проводится повторный аудит

SMOKE прошёл большой путь: Cleanshot/SMC и Flat в Pine, Selective FE, Rolling Symbol Strength, Quality Score, Structure Learning, секторные циклы, MTF, 5m confirmation, paper-server и causal-hardening.

После исправления подглядывания выяснилось, что часть прежних сильных результатов была недостоверна. Однако это не означает, что все старые идеи были плохими. Некоторые из них:

- тестировались на синтетических сделках;
- использовали историю сделки до фактического `exit_time`;
- переносились из matrix в WFO не полностью;
- оценивались на фиксированном заранее удачном core;
- блокировались общей статистикой другого setup-типа;
- проверялись одним глобальным рубильником вместо режимной маршрутизации;
- были описаны, но никогда не дошли до полноценной causal-симуляции.

Цель аудита — восстановить все идеи, отделить слабые идеи от слабых тестов и заново проверить разумные гипотезы на закрытых свечах и строгом OOS.

## 2. Критерии достоверности старого результата

Старый результат признаётся доказательным только при одновременном выполнении условий:

1. Использованы реальные закрытые свечи Binance Futures.
2. При принятии решения учитывались только сделки с `exit_time <= decision_time`.
3. Warm-up использовался только для обучения, а PnL считался только внутри OOS.
4. В WFO переносилась полная конфигурация matrix-кандидата.
5. Не использовался вручную подобранный список монет как доказательство универсальности.
6. PF считался по общему пулу прибыли и убытков, а не усреднением значений `99` по редким фолдам.
7. Одновременные кандидаты выбирались по causal-качеству, а не по алфавиту символа.
8. После разработки проводился замороженный внешний holdout без повторного перебора.

Большинство результатов до causal-hardening не выполняет весь этот список. Их цифры являются исторической диагностикой, а не доказательством edge.

## 3. Хронология проекта

### 3.1. До репозитория SMOKE

Исторические направления:

- Cleanshot / Smart Money: FVG, Order Block, fractals, RSI divergence, volume profile, liquidity raids, 4H/1D context.
- Flat v7.1/v7.2: Donchian range, ATR buffer, dynamic volume, запрет центра диапазона, fractal SL, swing TP.
- Sniper Pro+, Попрыгунчик, DynPA Router, Regime → Setup → Trigger → Risk.
- 15m trigger и более точный 5m entry.
- Сжатая цель для countertrend и более широкая цель по тренду.

Эти идеи не были полноценно перенесены в единый causal Python-тестер. Они не считаются опровергнутыми.

### 3.2. Selective FE и широкий universe

Тесты u8/u20/u40/u80 показали важную тенденцию: при механическом расширении списка монет edge размывался. Отсюда появилась идея TRUE Symbol Strength и rolling selector.

Старые абсолютные доходности этого этапа не признаются доказательными, но вывод о необходимости динамического отбора universe остаётся логичным.

### 3.3. Начало Smoke Strategy Lab

Первоначальная архитектура репозитория:

`trade CSV → rolling symbol selection → capital simulation → report`.

Первая центральная идея — Rolling Symbol Strength. Затем добавились Trade Quality Score, Structure Learning и Full Strategy Assembly.

### 3.4. Quality, Structure и связующая метрика

Trade Quality Score включал:

- symbol strength;
- trend alignment;
- volatility fit;
- target realism;
- entry quality;
- итоговый trade confidence;
- risk modifier;
- compressed/wider target policy.

Structure Learning включал exact/fallback/loose/global историю по setup, trend, volatility, structure, risk bucket и session.

Архитектура была перспективной, но ранние реализации могли использовать результат ещё не закрытой сделки. Кроме того, global/loose статистика могла жёстко блокировать новый setup. Поэтому старые цифры сборки недействительны, но сами слои должны быть повторно проверены в causal-soft режиме.

### 3.5. Regime-aware setup generator

Изначально генератор разделял пять самостоятельных семейств:

- breakout / breakdown continuation;
- trend pullback;
- range rotation;
- liquidity reclaim;
- ignition.

Позже исследования часто превращали их в один глобальный allow/block список. Например, range rotation был заблокирован после слабости в одном диагностическом фолде. После обнаруженных causal-ошибок это не является достаточным основанием навсегда удалять семейство.

### 3.6. Dynamic universe и sector rotation

Были реализованы:

- секторные группы;
- sector universe builder;
- sector research cycle;
- dynamic universe candidates;
- rolling ranking.

Правильная роль этих слоёв — ранжирование и контекст. Они не должны становиться ручным cherry-pick или вечным запретом целого сектора.

### 3.7. MTF и 5m

MTF 1D/4H context + 15m entry дал сильные старые результаты, но после causal-hardening baseline не подтвердился.

5m как обязательный gate уменьшал выборку и был отклонён. Это не опровергает 5m как:

- точку более точного входа;
- timing score;
- ограничение риска;
- дополнительный журналируемый признак без полного запрета сделки.

## 4. Пересмотр всех ключевых идей

| Идея | Старый статус | Достоверность старого теста | Новое решение |
|---|---|---:|---|
| Fixed core из заранее сильных монет | Давал сильные цифры | Низкая | Не возвращать как production-universe; оставить только контрольной группой |
| Rolling Symbol Strength | Центральная ранняя идея | Низкая/средняя | Повторить как soft ranking и отдельно как top-5/top-8 gate |
| Trade Quality Score | Сильные старые отчёты | Низкая из-за lookahead | Повторить causal; сначала как risk/ranking, не глобальный veto |
| Structure Learning | Сильные старые отчёты | Низкая из-за lookahead и global veto | Повторить exact/fallback; loose/global не имеют права полного запрета |
| Связующий confidence score | Не доведён до финального решения | Не проверен | Высокий приоритет; связать context/setup/entry/target, но не обучать на будущем |
| Regime router | Частично заменён глобальными фильтрами | Недостаточно проверен | Высший приоритет: раздельные правила для trend/range/high-volatility |
| Pullback | Стал основой последних тестов | Проверен лучше остальных, но нестабилен | Оставить одним из setup, не всей стратегией |
| Pullback resumption | Слишком редкий | Честный, но узкий тест | Оставить как отдельный строгий подтип, не заменять им весь pullback |
| Ignition | То разрешался, то блокировался | Старые выводы недействительны | Повторить отдельно и внутри trend router |
| Breakout | Часто глобально блокировался | Недостаточно causal-доказательств | Повторить отдельно; high-volatility не блокировать автоматически |
| Range rotation | Заблокирован после слабого фолда | Недостаточно | Повторить только в подтверждённом range и у границ диапазона |
| Liquidity reclaim | Был заблокирован baseline | Недостаточно | Повторить отдельно по low/high sweep событиям |
| Dynamic targets | Были политики, но не полноценная симуляция | Не проверено | Реализовать: wider trend, compressed countertrend, opposite range boundary |
| Flat v7.2 | Остался в Pine-линии | Не проверен в SMOKE | Перенести в Python как самостоятельный range setup и causal-тест |
| 5m confirmation | Hard gate дал мало сделок | Hard gate опровергнут | Не возвращать hard gate; проверить timing/risk score |
| Sector rotation | Архитектура создана | Недостаточно | Повторить как динамический rank/context, не hard allowlist |
| TRUE Symbol Strength | Была концепция | Не доведена | Считать только по реально завершённым и фактически исполненным/доступным сигналам |
| Long/Short единым baseline | Показал режимную зависимость | Неустойчив | Разрабатывать LONG и SHORT отдельно, затем объединять портфельным маршрутизатором |
| Countertrend target compression | Обсуждалась и была в политиках | Не проверена | Реализовать и тестировать отдельно |
| Cleanshot SMC: FVG/OB/fractals/liquidity raid | Ушёл из приоритета | Не опровергнут | Не возвращать пакетом; формализовать и тестировать по одному признаку |
| Daily liquidity raid + 4H VC/RB + 1H trigger | Пользовательская идея/схемы | Не реализовано | Отдельная будущая setup-family после формализации без визуальной субъективности |
| Sniper Pro+, Попрыгунчик, DynPA Router | Исторические направления | Нет единого causal-теста | Найти/восстановить точные правила, затем тестировать отдельными кандидатами |
| Automatic Feature Engineering | Старые циклы были нестабильны | Недостаточно | Только после создания чистого набора базовых гипотез; без black-box подгонки |
| Высокое плечо и агрессивный reinvest | Обсуждались | Риск не соответствует текущей задаче | Не возвращать на этапе поиска edge |
| AI black-box как финальный решатель | Обсуждался | Неаудируемо | Не использовать как торговый veto; допустим только текстовый анализ после доказанного baseline |

## 5. Первая волна повторного тестирования

Первый causal historical recheck использует только идеи, которые уже можно проверить без субъективной разметки:

1. Pullback family — hard и soft Quality/Structure.
2. Ignition отдельно.
3. Breakout отдельно.
4. Range rotation отдельно.
5. Liquidity reclaim отдельно.
6. Все setup-семейства вместе как естественный regime router.
7. Trend-family router: breakout + pullback + ignition.
8. Reversal/range router: range rotation + liquidity reclaim.
9. Rolling top-5 и top-8 поверх soft regime router.
10. Раздельная статистика LONG и SHORT.

Одинаковые условия для всех кандидатов:

- официальные Binance USD-M Futures archives;
- только закрытые 15m свечи;
- completed 4H/1D context;
- strict OOS;
- warm-up не входит в доходность;
- pooled PF;
- одинаковый портфель и комиссии;
- 12-часовой cooldown на символ;
- никаких live/API keys.

## 6. Вторая волна — требует новой реализации

После первой волны:

1. Dynamic target policies.
2. Python-порт Flat v7.2.
3. 5m timing/risk overlay без hard gate.
4. Sector strength как soft rank.
5. TRUE Symbol Strength по закрытым causal-сделкам.
6. Формализация liquidity raid / 4H VC / 1H trigger.
7. Отдельные LONG и SHORT risk/target models.

## 7. Что считается окончательно запрещённым

- реальный live до положительного внешнего holdout и paper-review;
- выбор production baseline по одному удачному фолду;
- ручной выбор только прибыльных символов;
- усреднение PF с искусственными значениями `99`;
- global/loose history как право жёстко блокировать новый setup;
- изменение правил после просмотра внешнего holdout;
- повторное использование holdout как подтверждения после настройки на нём;
- высокое плечо как способ скрыть отсутствие edge.

## 8. Новая исследовательская последовательность

`исторический реестр → family screening → regime router → dynamic exits → symbol/sector ranking → frozen external holdout → paper-review`.

До прохождения этой последовательности в сервере не должно быть подтверждённого торгового baseline. Сохраняются только инфраструктура, causal-слои, closed-candle storage, панель и установщик.
