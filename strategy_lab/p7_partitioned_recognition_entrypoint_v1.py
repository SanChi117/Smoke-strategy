#!/usr/bin/env python3
"""Technical entrypoint for exact P7 symbol-fold partition execution.

Installs the already tested P6 side-enum compatibility layer and the exact
incremental P1 POI transport before delegating to the frozen partition runner.
When P7_LEVELS_FILE is set, the exact symbol-level precompute produced by
p7_precomputed_levels_v1.py is reused instead of recomputed in every fold job.
Recognition semantics, thresholds, lifecycle, fingerprints and no-outcome scope
remain unchanged.
"""
from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path

# Import for technical compatibility side effects:
# 1) normalize FusionInput.side contract strings to the frozen P6 Direction enum;
# 2) install the exact incremental POI adapter on the shared P7 runner module.
import strategy_lab.p7_full_recognition_entrypoint_v1 as _compat  # noqa: F401,E402
import strategy_lab.p7_full_recognition_runner_v1 as _runner  # noqa: E402


def _install_precomputed_levels() -> None:
    value = os.environ.get("P7_LEVELS_FILE")
    if not value:
        return
    path = Path(value)
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if payload.get("recognition_id") != _runner.RECOGNITION_ID:
        raise ValueError("precomputed level recognition id mismatch")

    manifest_path = _runner.DATA_ROOT / "p7_full_recognition_data_manifest_v1.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if payload.get("data_manifest_sha256") != manifest_sha:
        raise ValueError("precomputed level manifest mismatch")

    expected_symbol = os.environ.get("P7_LEVELS_SYMBOL", "").upper()
    if expected_symbol and payload.get("symbol") != expected_symbol:
        raise ValueError("precomputed level symbol mismatch")

    levels = payload["levels"]

    def _precomputed_levels(_engine, symbol, _boundaries, _config):
        if symbol.upper() != payload["symbol"]:
            raise ValueError("precomputed levels requested for wrong symbol")
        return levels

    _runner._precompute_levels = _precomputed_levels


_install_precomputed_levels()
from strategy_lab.p7_partitioned_recognition_v1 import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
