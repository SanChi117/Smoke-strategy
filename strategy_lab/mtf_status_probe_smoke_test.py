#!/usr/bin/env python3
"""Smoke tests for the artifact-only SMOKE MTF V2 status probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_smoke_mtf_v2_real_recognition.py"
SPEC = importlib.util.spec_from_file_location("smoke_mtf_v2_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_forbidden_outcome_detection() -> None:
    clean = {"summary": {"selected_snapshots": 4}, "rows": [{"planned_rr": 2.0}]}
    dirty = {"rows": [{"future_return": 3.2}, {"metrics": {"mfe": 1.0}}]}
    assert PROBE._walk_forbidden(clean) == []
    found = PROBE._walk_forbidden(dirty)
    assert any("future_return" in path for path in found)
    assert any("mfe" in path for path in found)


def test_status_render_is_traceable() -> None:
    body = PROBE._render(
        {
            "target_sha": "abc123",
            "run": {
                "id": 77,
                "html_url": "https://github.com/example/repo/actions/runs/77",
                "status": "completed",
                "conclusion": "success",
            },
            "jobs": [],
            "recognition": {
                "summary": {
                    "evaluated_15m_bars": 10,
                    "evaluated_side_snapshots": 20,
                    "qualifying_snapshots": 3,
                    "selected_snapshots": 2,
                    "reason_counts": {"WAIT_5M_BOS": 4},
                },
                "candidate_rows": 2,
                "by_side": {"long": 1, "short": 1},
                "by_state": {"ENTRY_READY": 2},
                "no_pnl_contract": "PASS",
            },
        }
    )
    assert PROBE.MARKER in body
    assert "abc123" in body
    assert "No-PnL/future-outcome contract: **PASS**" in body
    assert "WAIT_5M_BOS" in body


def main() -> int:
    test_forbidden_outcome_detection()
    test_status_render_is_traceable()
    print("SMOKE MTF V2 status probe tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
