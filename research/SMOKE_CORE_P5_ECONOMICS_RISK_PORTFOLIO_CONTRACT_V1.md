# SMOKE CORE 1.0 — P5 Economics / Risk / Portfolio Contract V1

## Scope

P5 evaluates whether a causally valid P4 execution candidate is economically and operationally admissible. It does not inspect trade outcomes, optimize thresholds from PnL, run recognition scans, place orders or enable paper/live execution.

## Frozen cost model

All calculations are parameterized and must include:

- entry fee;
- exit fee;
- entry slippage;
- exit slippage;
- expected funding for the planned holding window;
- explicit cost buffer.

`total_cost_pct` is the full round-trip expected cost expressed as a percentage of entry price.

## Minimum movement

`minimum_move_pct = max(4 * total_cost_pct, atr_floor_pct, liquidity_buffer_pct)`

A candidate is rejected when the selected target movement is smaller than the minimum movement.

## Net economics

P5 calculates without changing the target or stop selected by upstream semantics:

- gross reward;
- gross loss;
- effective net reward after all costs;
- effective net loss after all costs;
- net RR.

Hard rejections:

- target movement `<= 2 * total_cost_pct`;
- net RR `< 1.35`;
- non-positive effective net reward;
- invalid or non-causal target/stop dependency.

Conditional range:

- net RR `1.35–1.69` is allowed only when the upstream scenario score is at least `80`;
- preferred net RR is `>= 1.70`.

P5 must never move a target, tighten a stop or alter an entry to manufacture a passing RR.

## Position risk

Frozen defaults and limits:

- risk per position: `0.5%` of equity;
- maximum total open risk: `2.0%` of equity;
- isolated margin only;
- default leverage: `20x`;
- maximum leverage: `25x`;
- margin per position: `<= 10%` of equity;
- total used margin: `<= 25%` of equity;
- total notional exposure: `<= 2.5x` equity.

## Liquidation safety

The liquidation distance must satisfy:

`liquidation_distance >= 2 * stop_distance + cost_buffer`

Failure is a hard risk rejection. P5 does not rely on exchange cross-margin rescue assumptions.

## Portfolio constraints

P5 groups correlated instruments into clusters and evaluates simultaneous candidates using:

- current open risk;
- current used margin;
- current total notional;
- cluster concentration;
- candidate quality and net economics.

When several candidates compete for limited capacity, ranking is deterministic and must use only information available at evaluation time. No outcome, PnL or future return fields are permitted.

## Outputs

Each evaluation must expose:

- exact upstream candidate and dependency ids;
- complete cost breakdown;
- minimum movement components;
- gross and net economics;
- leverage and liquidation checks;
- position size, margin and notional calculations;
- portfolio and correlation-cluster checks;
- decision: `PASS`, `CONDITIONAL_PASS`, `REJECT_ECONOMICS`, or `REJECT_RISK`;
- machine-readable reasons;
- no-outcome serialization.

## Causality and prohibitions

- closed data and current account state only;
- no future bars or trade outcomes;
- no threshold tuning from profitability;
- no recognition scan;
- no development backtest;
- no holdout, paper, VPS execution or live trading.

P6 is forbidden before P5 compile, semantic tests, upstream regressions, frozen-default checks and no-outcome guard are all green.
