#!/usr/bin/env python3
"""Checkpoint transport for Candidate 2 causal replay.

This module changes execution topology only. It reuses the exact validated P7
IncrementalPOIProvider but permits its causal runtime state to be serialized at
segment boundaries and restored by the next segment. No recognition semantics,
thresholds, evidence, lifecycle, fingerprints, or future-data scope are changed.
"""
from __future__ import annotations

from typing import Any

from strategy_lab.p7_incremental_poi_adapter_v1 import IncrementalPOIProvider

_PROVIDERS: dict[int, IncrementalPOIProvider] = {}
_INSTALLED = False


def install(runner_module: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    def _active_pois(engine: Any, timestamp: Any, _unused_poi_engine: Any):
        key = id(engine)
        provider = _PROVIDERS.get(key)
        if provider is None:
            provider = IncrementalPOIProvider(engine)
            _PROVIDERS[key] = provider
        return provider.advance(timestamp)

    runner_module._active_pois = _active_pois
    runner_module._c2_checkpoint_poi_installed = True
    _INSTALLED = True


def restore_provider(engine: Any, provider: IncrementalPOIProvider) -> None:
    _PROVIDERS[id(engine)] = provider


def get_provider(engine: Any) -> IncrementalPOIProvider:
    provider = _PROVIDERS.get(id(engine))
    if provider is None:
        provider = IncrementalPOIProvider(engine)
        _PROVIDERS[id(engine)] = provider
    return provider


__all__ = ["install", "restore_provider", "get_provider"]
