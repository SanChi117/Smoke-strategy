# Strategy Universe Layer

This is a metadata/universe layer only. It does not change the strategy, baseline, filters, risk logic, paper mode, or execution.

## Policy

- Strategy changed: `False`
- Sector is trading rule: `False`
- Sector is context tag: `True`
- Live trading: `False`
- Order execution: `False`

## Core reference symbols

INJUSDT, TONUSDT, DOGEUSDT, ARBUSDT, NEARUSDT, OPUSDT

## Combined universe

- total symbols: 34
- discovery symbols: 28

```text
INJUSDT,TONUSDT,DOGEUSDT,ARBUSDT,NEARUSDT,OPUSDT,BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,POLUSDT,FETUSDT,RENDERUSDT,TAOUSDT,FILUSDT,ARUSDT,UNIUSDT,AAVEUSDT,LDOUSDT,ONDOUSDT,PENDLEUSDT,OMUSDT,SHIBUSDT,PEPEUSDT,IMXUSDT,SANDUSDT,MANAUSDT,LINKUSDT,PYTHUSDT,API3USDT,XRPUSDT,LTCUSDT,BCHUSDT,JUPUSDT
```

## Sector counts as tags

- ai_data_compute: 3
- defi_dex_lending: 3
- depin_infrastructure: 3
- gaming_metaverse: 3
- layer1_smart_contracts: 3
- layer2_scaling: 3
- majors_liquid: 3
- memes_high_beta: 3
- oracles_data_services: 3
- payments_legacy_value: 3
- rwa_tokenization: 3
- solana_ecosystem: 3

## Symbols

- **INJUSDT**: role=core, sectors=untagged
- **TONUSDT**: role=core, sectors=untagged
- **DOGEUSDT**: role=core, sectors=memes_high_beta
- **ARBUSDT**: role=core, sectors=layer2_scaling
- **NEARUSDT**: role=core, sectors=untagged
- **OPUSDT**: role=core, sectors=layer2_scaling
- **BTCUSDT**: role=discovery, sectors=majors_liquid
- **ETHUSDT**: role=discovery, sectors=majors_liquid, layer1_smart_contracts
- **SOLUSDT**: role=discovery, sectors=majors_liquid, layer1_smart_contracts, solana_ecosystem
- **BNBUSDT**: role=discovery, sectors=layer1_smart_contracts
- **POLUSDT**: role=discovery, sectors=layer2_scaling
- **FETUSDT**: role=discovery, sectors=ai_data_compute
- **RENDERUSDT**: role=discovery, sectors=ai_data_compute, depin_infrastructure
- **TAOUSDT**: role=discovery, sectors=ai_data_compute
- **FILUSDT**: role=discovery, sectors=depin_infrastructure
- **ARUSDT**: role=discovery, sectors=depin_infrastructure
- **UNIUSDT**: role=discovery, sectors=defi_dex_lending
- **AAVEUSDT**: role=discovery, sectors=defi_dex_lending
- **LDOUSDT**: role=discovery, sectors=defi_dex_lending
- **ONDOUSDT**: role=discovery, sectors=rwa_tokenization
- **PENDLEUSDT**: role=discovery, sectors=rwa_tokenization
- **OMUSDT**: role=discovery, sectors=rwa_tokenization
- **SHIBUSDT**: role=discovery, sectors=memes_high_beta
- **PEPEUSDT**: role=discovery, sectors=memes_high_beta
- **IMXUSDT**: role=discovery, sectors=gaming_metaverse
- **SANDUSDT**: role=discovery, sectors=gaming_metaverse
- **MANAUSDT**: role=discovery, sectors=gaming_metaverse
- **LINKUSDT**: role=discovery, sectors=oracles_data_services
- **PYTHUSDT**: role=discovery, sectors=oracles_data_services, solana_ecosystem
- **API3USDT**: role=discovery, sectors=oracles_data_services
- **XRPUSDT**: role=discovery, sectors=payments_legacy_value
- **LTCUSDT**: role=discovery, sectors=payments_legacy_value
- **BCHUSDT**: role=discovery, sectors=payments_legacy_value
- **JUPUSDT**: role=discovery, sectors=solana_ecosystem
