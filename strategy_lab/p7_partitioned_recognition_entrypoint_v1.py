#!/usr/bin/env python3
"""Technical entrypoint for exact P7 symbol-fold partition execution.

Installs the already tested P6 side-enum compatibility layer and the exact
incremental P1 POI transport before delegating to the frozen partition runner.
Recognition semantics, thresholds, lifecycle, fingerprints and no-outcome scope
remain unchanged.
"""
from __future__ import annotations

# Import for technical compatibility side effects:
# 1) normalize FusionInput.side contract strings to the frozen P6 Direction enum;
# 2) install the exact incremental POI adapter on the shared P7 runner module.
import strategy_lab.p7_full_recognition_entrypoint_v1 as _compat  # noqa: F401,E402
from strategy_lab.p7_partitioned_recognition_v1 import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
