#!/usr/bin/env python3
"""Regression test for relevant-vs-unrelated structure history."""

from __future__ import annotations

from strategy_lab.causal_history import structure_decision_for_scope
from strategy_lab.structure_learning import StructureLearningConfig, StructureStats


def stats(scope: str, score: float, trades: int = 30) -> StructureStats:
    return StructureStats(scope, "test", trades, 0.25, -0.4, 0.5, 5, score)


def main() -> int:
    cfg = StructureLearningConfig(take_threshold=64.0, watch_threshold=52.0)

    # Relevant exact history is permitted to veto a demonstrably weak pattern.
    decision, effective = structure_decision_for_scope(stats("exact", 20.0), cfg)
    assert decision == "SKIP"
    assert effective == 20.0

    # Unrelated/global history is context only and must not kill a new setup type.
    for scope in ("loose", "global", "cold_start"):
        decision, effective = structure_decision_for_scope(stats(scope, 5.0), cfg)
        assert decision == "WATCH", (scope, decision)
        assert effective >= cfg.watch_threshold, (scope, effective)

    # A strong setup-specific history is still a TAKE.
    decision, _effective = structure_decision_for_scope(stats("fallback", 75.0), cfg)
    assert decision == "TAKE"

    print("structure_scope_smoke_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
