#!/usr/bin/env python
"""Convenience entry point that works without installing the package.

    python run_backtest.py backtest --symbols 005930,000660 --days 20
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from supertrend_ema100.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
