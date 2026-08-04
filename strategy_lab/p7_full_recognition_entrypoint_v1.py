#!/usr/bin/env python3
"""Technical entrypoint for the exact P7 runner.

The initial transport of the P7 runner encoded ``FusionInput.side`` as its
contract value (``LONG``/``SHORT``). P6 stores that field as an Enum and its
stable fingerprint helper dereferences ``.value``. This compatibility layer
normalizes only that API representation before invoking the frozen P6 helper.

P7 additionally installs an exact causal incremental POI adapter. The frozen
P1 implementation and all recognition semantics stay unchanged; only repeated
historical recomputation is replaced by sequential closed-bar state updates.
"""
from __future__ import annotations

from dataclasses import replace

import strategy_lab.scenario_fusion_v1 as scenario_fusion

_original_build_fingerprint = scenario_fusion.build_fingerprint


def _contract_compatible_build_fingerprint(data):
    if isinstance(data.side, str):
        data = replace(data, side=scenario_fusion.Direction(data.side))
    return _original_build_fingerprint(data)


scenario_fusion.build_fingerprint = _contract_compatible_build_fingerprint

import strategy_lab.p7_full_recognition_runner_v1 as _runner  # noqa: E402
from strategy_lab.p7_incremental_poi_adapter_v1 import (  # noqa: E402
    install_incremental_poi_adapter,
)

install_incremental_poi_adapter(_runner)
main = _runner.main


if __name__ == "__main__":
    raise SystemExit(main())
