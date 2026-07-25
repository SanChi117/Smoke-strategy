# SMOKE CORE 1.0 — P4 Flexible 5m/15m Execution Structure Contract V1

## Scope

P4 is a causal recognition layer that converts an exact confirmed P3 anchor event into a local 5m/15m execution-structure state. It does not calculate PnL, position size, leverage, liquidation, portfolio allocation or trade outcomes.

## Inputs

- closed 5m and 15m bars only;
- one exact P3 `anchor_event_id` linked to a specific POI and/or liquidity level;
- anchor direction, anchor confirmation time and anchor invalidation state;
- confirmed local pivots available at evaluation time.

## Anchored local structure

Local structure starts at the active anchor event. Arbitrary nearby BOS/CHOCH events cannot be attached to a scenario. P4 derives:

- reaction leg;
- protected swing;
- weak swing;
- local dealing range;
- displacement and acceptance state;
- retest state;
- expiry and invalidation.

## Confirmation modes

### Mode A — Textbook break

A closed 5m or 15m candle breaks the anchored protected swing with displacement and directional close. Confirmation time is that candle close.

### Mode B — Acceptance plus retest

Price closes beyond the anchored structure boundary, remains accepted, and subsequently retests the boundary without invalidating the anchor. Confirmation time is the retest candle close.

### Mode C — Displacement plus failed retest

A displacement leg leaves the anchored area and a later counter-directional attempt fails to reclaim the origin/boundary. Confirmation time is the failed-retest candle close.

## Timeframe semantics

- 5m refines timing and local geometry.
- 15m stabilizes structure and may confirm a mode independently.
- 5m/15m disagreement is a soft confidence conflict unless it creates a causal invalidation.
- Unclean BOS/CHOCH lowers confidence; it is not an automatic hard block.

## Entry-policy outputs

P4 emits recognition-only entry-policy candidates by scenario family. It does not place orders.

- Raid reversal: next closed-bar open after confirmed Mode A/B/C, with no retroactive fill.
- Trend continuation: first valid retest after confirmed continuation structure, with no retroactive fill.
- Range rotation: confirmed rejection/failed acceptance from an anchored range extreme, with no retroactive fill.

Each output includes exact `anchor_event_id`, confirmation mode, confirmation timestamp, eligible-from timestamp, expiry timestamp, protected swing, invalidation boundary, confidence, conflicts and evidence provenance.

## Lifecycle

`DISCOVERED → REACTION_FORMED → STRUCTURE_CONFIRMED → ENTRY_ELIGIBLE`

Terminal states:

- `EXPIRED`;
- `INVALIDATED`;
- `CONSUMED`.

No state may appear before its confirming candle closes. Expired or invalidated structures cannot become eligible later.

## Hard blocks

Only:

- missing or non-confirmed anchor;
- anchor already expired/invalidated;
- insufficient closed-bar data;
- impossible causal ordering;
- missing protected swing or invalidation boundary.

## Required tests

- exact anchor binding and rejection of arbitrary nearby events;
- causal reaction-leg construction;
- protected-swing confirmation timing;
- Mode A long/short;
- Mode B long/short;
- Mode C long/short;
- 5m/15m disagreement as soft conflict;
- unclean BOS/CHOCH as confidence penalty;
- expiry and invalidation terminal behavior;
- no retroactive entry eligibility;
- deterministic IDs;
- evidence provenance preservation;
- no-PnL/outcome serialization guard;
- P3/P2/P1 regression tests.

## Exit gate

P4 is complete only after compile, P4 semantic tests, P3/P2/P1 regressions, reused causal primitive tests, frozen-contract guard and no-outcome guard are green. P5 is forbidden before this gate.
