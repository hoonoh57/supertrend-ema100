"""Supertrend-EMA100 breakout backtest engine.

Implements the specification in ``plan.txt``: continuous intraday indicators,
tick-strength features with prior-day baselines, a per-symbol entry/exit state
machine, counterfactual logging and a portfolio layer.
"""

from __future__ import annotations

from .config import BacktestConfig

__version__ = "0.1.0"
__all__ = ["BacktestConfig", "__version__"]
