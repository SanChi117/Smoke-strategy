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
import json
import os
import pickle
from pathlib import Path
from typing import Any, Mapping

# Import for technical compatibility side effects:
# 1) normalize FusionInput.side contract strings to the frozen P6 Direction enum;
# 2) install the exact incremental POI adapter on the shared P7 runner module.
import strategy_lab.p7_full_recognition_entrypoint_v1 as _compat  # noqa: F401,E402
import strategy_lab.p7_full_recognition_runner_v1 as _runner  # noqa: E402


def _authoritative_transport_contract_matches(
    payload: Mapping[str, Any], manifest: Mapping[str, Any]
) -> bool:
    """Validate the immutable dataset contract when gzip transport bytes differ.

    Canonical gzip files embed a creation timestamp, so re-acquiring the same
    immutable Binance Vision archives can change the raw manifest SHA solely
    through canonical gzip byte hashes. This fallback verifies every frozen
    semantic data boundary available to the precomputed-level payload.
    """
    symbol = str(payload.get("symbol", "")).upper()
    canonical = manifest.get("canonical_files", {})
    row = canonical.get(symbol, {}) if isinstance(canonical, Mapping) else {}
    return (
        payload.get("recognition_id") == _runner.RECOGNITION_ID
        and manifest.get("recognition_id") == _runner.RECOGNITION_ID
        and payload.get("source") == manifest.get("source")
        and payload.get("interval") == manifest.get("interval") == "5m"
        and manifest.get("start_inclusive") == "2024-01-01T00:00:00+00:00"
        and manifest.get("end_inclusive") == "2024-06-30T23:55:00+00:00"
        and manifest.get("archive_count") == 30
        and manifest.get("symbols")
        == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT"]
        and manifest.get("months")
        == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
        and symbol in manifest.get("symbols", ())
        and int(payload.get("boundary_count", -1)) == 17472
        and int(row.get("row_count", -1)) == 52416
        and str(row.get("first_open_time", "")).startswith("2024-01-01T00:00:00")
        and str(row.get("last_open_time", "")).startswith("2024-06-30T23:55:00")
    )


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
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if payload.get("data_manifest_sha256") != manifest_sha:
        manifest = json.loads(manifest_bytes)
        if not _authoritative_transport_contract_matches(payload, manifest):
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
