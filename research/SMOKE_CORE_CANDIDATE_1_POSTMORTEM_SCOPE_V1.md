# SMOKE CORE Candidate 1 — Post-Mortem Scope V1

Этот этап является только диагностическим разбором единственного authoritative development profitability test Candidate 1.

Источник истины:
- run `31130707800`;
- artifact `smoke-core-candidate-1-development-profitability-v1`;
- verdict `FAIL`;
- decision `CLOSE_CANDIDATE_1_WITHOUT_TUNING`;
- 909 closed trades;
- 50 authoritative symbol-fold profitability partitions;
- original locked P7 dataset.

Разрешено:
- воспроизвести те же 909 portfolio-accepted trades;
- разбить результаты по symbol, direction, family, fold, score bucket, raw RR, stop distance и holding time;
- определить крупнейшие источники убытка;
- сформулировать исследовательские гипотезы для отдельной Candidate 2.

Запрещено:
- менять Candidate 1;
- повторно оценивать Candidate 1 с изменёнными threshold/weights/families/symbols/directions/stops/targets/costs/risk/portfolio rules;
- объявлять любой поднабор из уже увиденного development dataset новой прибыльной стратегией;
- запускать второй authoritative development profitability test Candidate 1;
- использовать untouched holdout, paper/live/VPS/real orders.

Любые наблюдения этого post-mortem являются exploratory и могут использоваться только для проектирования новой Candidate 2, которая должна получить собственный preregistration и новый допустимый evaluation design.