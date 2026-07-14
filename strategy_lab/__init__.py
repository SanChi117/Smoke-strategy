"""Smoke Strategy Lab package."""

# Import and patch the adaptive layers before other modules consume them. This
# keeps one public API while enforcing causal/no-lookahead history everywhere.
from strategy_lab import rolling_symbol_strength as _rolling_symbol_strength
from strategy_lab import structure_learning as _structure_learning
from strategy_lab import trade_quality_score as _trade_quality_score
from strategy_lab.causal_history import apply_causal_patches as _apply_causal_patches
from strategy_lab.closed_context import apply_closed_context_patch as _apply_closed_context_patch

_apply_causal_patches()
_apply_closed_context_patch()

__all__ = [
    "config",
    "schemas",
    "market_data",
    "market_data_adapter",
    "data_quality",
    "data_quality_cli_smoke_test",
    "universe_input",
    "universe_input_smoke_test",
    "feature_builder",
    "setup_generator",
    "risk_model",
    "candle_exit_simulator",
    "exit_diagnostics",
    "candle_research_report",
    "candle_pipeline",
    "candle_pipeline_smoke_test",
    "report_sanity",
    "report_sanity_cli_smoke_test",
    "end_to_end_pipeline",
    "end_to_end_smoke_test",
    "walk_forward",
    "walk_forward_smoke_test",
    "parameter_grid",
    "parameter_grid_smoke_test",
    "paper_mode",
    "paper_review",
    "paper_mode_smoke_test",
    "research_server",
    "research_server_smoke_test",
    "regime_samples_smoke_test",
    "regime_batch_smoke_test",
    "local_demo_smoke_test",
    "rolling_symbol_strength",
    "trade_quality_score",
    "structure_learning",
    "causal_history",
    "closed_context",
    "decision_engine",
    "live_market",
    "strategy_assembly",
    "universe_selector",
    "portfolio_simulator",
    "risk_diagnostics",
    "validation",
    "pipeline",
    "pipeline_smoke_test",
]
