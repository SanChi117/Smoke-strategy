# Strategy Universe Layer

## Purpose

The universe/sector layer is a separate metadata layer above the strategy.

It does **not** change the strategy rules, baseline, filters, risk model, paper mode, signal mode, or execution.

The goal is simple:

1. Keep the proven/reference strategy intact.
2. Keep the old strong core as a control set.
3. Add more liquid/trending coins into a discovery pool.
4. Attach sector/narrative tags to every coin.
5. Let the strategy select trades by its own filters.
6. Use sector tags only to understand market context and current rotation.

## Correct mental model

```text
strategy baseline
+ core reference symbols
+ discovery pool from sector/liquidity lists
+ sector/narrative tags
= larger tagged universe for research/signals
```

Sector groups are not trading rules.

```text
WRONG:
strong sector -> trade only this sector

RIGHT:
all tagged symbols -> strategy filters -> selected symbols -> report sector context
```

## Files

- `strategy_lab/universe/sector_groups.json` — seed sector/narrative groups.
- `scripts/build_strategy_universe_layer.py` — builds tagged strategy universe.
- `results/strategy_universe_layer/strategy_universe_layer.md` — human-readable report.
- `results/strategy_universe_layer/strategy_universe_layer.json` — machine-readable layer.
- `results/strategy_universe_layer/strategy_universe_tags.csv` — symbol tags.
- `results/strategy_universe_layer/combined_symbols.txt` — core + discovery symbols.
- `results/strategy_universe_layer/core_reference_symbols.txt` — old reference/control core.
- `results/strategy_universe_layer/discovery_symbols.txt` — extra symbols from groups.

## Manual command

```bash
python scripts/build_strategy_universe_layer.py --top-n-per-group 10
```

Optional:

```bash
python scripts/build_strategy_universe_layer.py \
  --top-n-per-group 10 \
  --extra-symbols "RAYUSDT,JTOUSDT" \
  --exclude-symbols "XMRUSDT"
```

## Next research usage

Use the combined symbols file as input to the existing research runner, but do not change the strategy rules just because a symbol belongs to a sector.

```bash
python scripts/run_deep_research_suite.py \
  --symbols-file results/strategy_universe_layer/combined_symbols.txt \
  --interval 1h \
  --limit 1500 \
  --windows 4 \
  --root results/tagged_universe_research
```

The result should be interpreted as:

```text
which symbols did the existing strategy choose?
what sectors/tags do those symbols belong to?
are new discovery coins useful or only noisy?
```

Not as:

```text
which sector should replace the strategy?
```

## Safety / scope

Research only. No API keys, no private account data, no order execution.
