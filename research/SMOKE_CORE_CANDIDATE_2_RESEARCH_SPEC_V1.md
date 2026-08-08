# SMOKE CORE Candidate 2 — Research Specification V1

## 0. Статус документа

Это **research specification**, а не profitability preregistration и не готовая стратегия.

Candidate 2 создаётся как новая торговая гипотеза после формального закрытия Candidate 1. Она наследует проверенную инфраструктуру SMOKE CORE P1–P8, но **не наследует торговые выводы Candidate 1 как готовые фильтры**.

Candidate 1 post-mortem используется только для генерации гипотез. Нельзя взять найденные на уже увиденном development dataset числа (например конкретный RR bucket, конкретный symbol или конкретное время удержания), превратить их в фильтр и затем объявить это подтверждённым edge.

## 1. Frozen infrastructure, которая переносится без переизобретения

Candidate 2 повторно использует как инфраструктурный фундамент:

- causal market-data visibility;
- P1 POI / imbalance representation;
- P2 context + liquidity representation;
- P3 interaction lifecycle;
- P4 execution / structure representation;
- P5 cost, risk and portfolio engine как независимый execution contract;
- P6 deterministic scenario transport;
- P7 outcome-blind recognition discipline;
- P8 exact semantic replay/freeze discipline;
- global fingerprint dedupe;
- immutable data manifests;
- no-future/no-outcome recognition boundary;
- deterministic replay and regression testing.

Candidate 2 не должна ослаблять эти свойства ради улучшения бэктеста.

## 2. Что Candidate 1 показал как problem statement

Post-mortem Candidate 1 показал следующие архитектурные проблемы, которые Candidate 2 обязана адресовать концептуально:

1. `LIQUIDITY_RAID_REVERSAL` генерировал подавляющую часть убытка.
2. LONG и SHORT не проявили симметричного поведения.
3. Текущий upstream score почти не разделял успешные и неуспешные допущенные сделки.
4. Очень дальняя theoretical target liquidity давала высокий nominal RR, но низкую вероятность реализации.
5. Большое количество ENTRY_READY сценариев рынок опровергал вскоре после входа.
6. Механическое изменение stop distance само по себе не объясняет провал.
7. Провал наблюдался почти во всех chronological folds, поэтому его нельзя списать на один плохой режим.

Эти наблюдения не являются готовыми правилами Candidate 2. Они задают задачи новой модели.

## 3. Главная гипотеза Candidate 2

**Торговый edge должен определяться не фактом наличия POI/raid/pullback сам по себе, а подтверждённым причинным переходом рынка из состояния возможности в состояние устойчивого принятия сценария с достижимой целью.**

То есть Candidate 2 не спрашивает только:

> "Есть ли хороший уровень + interaction + structure?"

Она дополнительно должна ответить:

> "Есть ли до входа доказательство, что рынок принимает направление сценария, и существует ли причинно достижимая цель внутри текущего regime/volatility horizon?"

## 4. Новые независимые компоненты Candidate 2

### 4.1 Regime State Engine

Новый `RegimeState` должен быть вычисляем только из данных, доступных на момент решения.

Минимальные состояния:

- `TREND_EXPANSION_UP`;
- `TREND_EXPANSION_DOWN`;
- `TREND_PULLBACK_UP`;
- `TREND_PULLBACK_DOWN`;
- `BALANCED_RANGE`;
- `VOLATILITY_TRANSITION`;
- `DISORDERED`.

Regime определяется не одной EMA/ADX-проверкой, а согласованностью нескольких причинных свойств:

- HTF/LTF directional structure alignment;
- slope/persistence структуры;
- realized volatility state относительно собственной истории;
- directional efficiency / overlap;
- displacement persistence;
- liquidity-location context;
- compression/expansion transition.

Точные формулы и thresholds должны быть определены **до** нового authoritative profitability evaluation.

### 4.2 Scenario Family Separation

Candidate 2 запрещает универсальную admission-логику для всех families.

Каждая family получает собственную state machine и собственные обязательные evidence classes.

#### A. Trend Pullback Continuation

Концептуальная последовательность:

`TREND REGIME -> IMPULSE -> CONTROLLED PULLBACK -> POI INTERACTION -> RE-ACCEPTANCE -> STRUCTURE CONFIRMATION -> ENTRY_READY`

Обязательные свойства:

- тренд существовал до pullback;
- impulse имеет directional efficiency, а не только размер;
- pullback не разрушает protected structure;
- реакция на POI должна сопровождаться повторным принятием направления;
- target должен быть достижим внутри актуального structural/volatility horizon.

#### B. Liquidity Raid Reversal

Raid не может стать ENTRY_READY просто из-за sweep + reclaim + локального BOS.

Новая последовательность:

`EXTREME LOCATION -> LIQUIDITY RAID -> FAILED CONTINUATION -> VALUE RE-ACCEPTANCE -> OPPOSITE DISPLACEMENT -> PERSISTENCE -> ENTRY_READY`

Обязательные evidence classes:

- raid происходит в причинно значимой extreme-location зоне;
- продолжение в направлении raid терпит неудачу;
- цена возвращается и удерживается внутри принятой value/structure области;
- противоположный displacement должен иметь follow-through;
- локальная структура должна сохраняться достаточное число причинных событий/баров, определённых в preregistration;
- immediate re-failure отменяет scenario до ENTRY_READY.

Candidate 2 не обязана включать Raid family в первый implementation milestone, если её causal state machine нельзя определить без post-hoc правил. В этом случае family остаётся `RESEARCH_ONLY`, а не молча удаляется как плохая по прошлому PnL.

### 4.3 Direction-Specific Policy

LONG и SHORT рассматриваются как отдельные causal policies.

Запрещено автоматически зеркалить:

- regime requirements;
- liquidity interpretation;
- volatility constraints;
- persistence evidence;
- target reachability assumptions.

При этом различия должны иметь рыночное/структурное обоснование, а не основываться на том, что SHORT был хуже в Candidate 1.

### 4.4 Acceptance / Persistence Engine

Новый компонент отвечает на вопрос: **сценарий подтверждён только мгновенным trigger или рынок реально удерживает новое состояние?**

Допустимые классы причинных evidence:

- closes retained beyond reclaimed structure;
- no immediate loss of protected micro-structure;
- follow-through after displacement;
- pullback depth after confirmation;
- directional efficiency after trigger;
- opposing wick/body rejection behavior;
- local value acceptance relative to causal anchor.

Компонент должен производить явный объект:

```text
PersistenceEvidence
- scenario_id
- evaluated_at
- accepted
- persistence_state
- evidence_ids
- invalidation_ids
- causal_window_start
- causal_window_end
```

Никакие MAE/MFE, future holding time, TP/SL outcome или будущие свечи не могут входить в этот объект.

### 4.5 Attainable Target Engine

Candidate 1 выбирал target прежде всего как структуру/ликвидность, доступную сценарию. Candidate 2 добавляет отдельную проверку **достижимости** цели.

Target candidate должен пройти все классы проверки:

1. structural relevance;
2. unobstructed path / intermediate opposing structure;
3. regime consistency;
4. volatility-normalized distance;
5. causal horizon compatibility;
6. cost-adjusted reward/risk.

Выход движка:

```text
TargetReachability
- target_id
- target_price
- structural_reason
- path_obstacles
- volatility_distance
- horizon_class
- reachable
- rejection_reasons
- evidence_ids
```

Важно: Candidate 2 не вводит post-hoc правило `RR < 2.5`. Диагноз Candidate 1 используется только как основание изменить саму модель выбора цели. Числовые границы будут preregistered независимо.

### 4.6 Quality Model V2

Старый upstream score нельзя просто повысить или понизить.

Новый score должен измерять **целостность конкретного scenario path**, а не сумму общих bullish/bearish evidence.

Предлагаемая семантика score:

- `regime_coherence`;
- `location_quality`;
- `interaction_quality`;
- `acceptance_persistence`;
- `structure_integrity`;
- `target_reachability`;
- `conflict_penalty`.

Каждая компонента обязана иметь самостоятельный causal provenance.

Score не должен использовать outcome-derived weights. Веса фиксируются до нового profitability evaluation.

## 5. Candidate 2 lifecycle

Новый lifecycle должен сделать ложные ранние входы видимым состоянием, а не сразу превращать их в сделку.

Минимальная машина состояний:

```text
DISCOVERED
  -> CONTEXT_VALID
  -> INTERACTION_ACTIVE
  -> STRUCTURE_CONFIRMED
  -> ACCEPTANCE_PENDING
  -> ACCEPTANCE_CONFIRMED
  -> TARGET_VALIDATED
  -> ENTRY_READY
```

Отмены:

```text
CANCELLED_REGIME
CANCELLED_INTERACTION
CANCELLED_STRUCTURE
CANCELLED_ACCEPTANCE
CANCELLED_TARGET
CANCELLED_ECONOMICS
CANCELLED_RISK
EXPIRED
```

Каждый transition должен иметь deterministic ID/provenance и replay equivalence.

## 6. Entry semantics

ENTRY_READY разрешён только после одновременного выполнения:

- family-specific causal sequence complete;
- RegimeState разрешает family/direction;
- PersistenceEvidence.accepted = true;
- protected structure remains valid;
- TargetReachability.reachable = true;
- P5 economics pass;
- P5 risk pass;
- no hard conflict;
- fingerprint/rearm rules satisfied.

Candidate 2 не должна оптимизировать частоту сделок. Если evidence недостаточно, корректный результат — `NO_SETUP` / cancellation.

## 7. Что нельзя переносить как фильтр из Candidate 1 post-mortem

Запрещено без нового независимого обоснования вводить:

- BTC LONG whitelist;
- LINK/ETH blacklist;
- SHORT ban;
- `RR < 2.5` rule;
- фильтр по будущему holding time;
- threshold upstream score, подобранный по Candidate 1 PnL;
- stop-distance bucket, подобранный по Candidate 1;
- отключение Raid только потому, что его исторический PF был низким.

Все такие наблюдения являются exploratory evidence о неполноте модели, а не параметрами новой стратегии.

## 8. Research milestones Candidate 2

### C2-P1 — Formal hypothesis contract

Зафиксировать:
- families in scope;
- direction policies;
- allowed causal inputs;
- forbidden outcome inputs;
- exact state-machine definitions.

### C2-P2 — Regime State Engine

Реализовать deterministic causal regime classification + smoke tests.

### C2-P3 — Acceptance/Persistence Engine

Реализовать explicit acceptance states, invalidation and provenance.

### C2-P4 — Attainable Target Engine

Реализовать target candidates, obstacle/path logic, volatility/horizon normalization.

### C2-P5 — Family Policies

Реализовать Trend policy и, только если specification sufficiently causal, Raid policy.

### C2-P6 — Quality Model V2

Зафиксировать components/weights/penalties до outcome evaluation.

### C2-P7 — Outcome-blind recognition

Проверить:
- no outcome leakage;
- deterministic fingerprints;
- dedupe;
- lifecycle completeness;
- sufficient recognition count.

### C2-P8 — Semantic replay/freeze

Exact replay parity = mandatory before profitability.

### C2-P9 — New development profitability

Только после отдельного preregistration и на новом допустимом development dataset/design.

### C2-P10 — External holdout

Только если C2-P9 PASS.

## 9. Evaluation-data rule

Jan–Jun 2024 по пяти текущим symbols уже использованы для Candidate 1 outcome inspection. Они могут использоваться для:

- implementation debugging без outcome conclusions;
- deterministic causal unit tests;
- replay regression;
- exploratory hypothesis development с явной маркировкой.

Они **не могут быть единственным authoritative profitability доказательством Candidate 2**.

Перед C2-P9 необходимо отдельно зафиксировать data provenance и выбрать development evaluation data, которое не превращает Candidate 1 post-mortem в повторную оптимизацию на том же результате.

Untouched external holdout должен быть определён и cryptographically frozen **до** C2-P9, но не открыт до development PASS.

## 10. Success philosophy

Candidate 2 считается улучшением не потому, что она выдаёт меньше стопов на Candidate 1 dataset, а если:

1. новая causal hypothesis сформулирована до проверки результата;
2. recognition semantics детерминированы и outcome-blind;
3. replay exact;
4. новый development test проходит заранее заданный gate;
5. результат затем воспроизводится на untouched external holdout.

## 11. Текущий следующий шаг

До написания торговых thresholds необходимо реализовать **C2-P1/C2-P2 skeleton**:

- typed RegimeState contract;
- typed PersistenceEvidence contract;
- typed TargetReachability contract;
- family policy interface;
- forbidden-field audit;
- deterministic serialization/provenance;
- smoke tests.

Только после этого фиксировать конкретные formulas/thresholds и preregistration Candidate 2.