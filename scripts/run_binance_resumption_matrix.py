#!/usr/bin/env python3
"""Focused matrix for causal pullback-resumption research candidates."""

from __future__ import annotations

import run_binance_tagged_mtf_fast_matrix as fast


CANDIDATE_NAMES = {
    "TAGGED_PULLBACK_SHORT_BALANCED_V1",
    "TAGGED_PULLBACK_RESUMPTION_BOTH_V1",
    "TAGGED_PULLBACK_RESUMPTION_BALANCED_V1",
    "TAGGED_PULLBACK_RESUMPTION_STRICT_V1",
    "TAGGED_PULLBACK_RESUMPTION_BOTH_VR09_V1",
}


def main() -> int:
    selected = [item for item in fast.MTF_SELECTED_CONFIGS if str(item.get("name")) in CANDIDATE_NAMES]
    missing = CANDIDATE_NAMES - {str(item.get("name")) for item in selected}
    if missing:
        raise SystemExit("Missing resumption configs: " + ", ".join(sorted(missing)))
    fast.MTF_FAST_CONFIGS = selected
    print("Focused resumption candidates: " + ", ".join(str(item["name"]) for item in selected), flush=True)
    return fast.main()


if __name__ == "__main__":
    raise SystemExit(main())
