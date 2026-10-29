"""Extension measures for the EXT delay filter and score penalty."""

from __future__ import annotations

import math
from typing import Sequence


def last_up_flip(direction: Sequence[int], i: int, fresh_bars: int) -> int | None:
    """Return the latest up-flip index within the fresh-bar window."""
    if i < 1 or i >= len(direction) or fresh_bars <= 0:
        return None

    stop = max(1, i - fresh_bars + 1)
    for k in range(i, stop - 1, -1):
        if direction[k] != 1:
            return None
        if direction[k - 1] == -1:
            return k
    return None


def extension_value(
    i: int,
    close: float,
    atr: float,
    st: float,
    direction: Sequence[int],
    st_upper: Sequence[float],
    *,
    ref: str,
    d_max: float,
    ext_max: float,
    fresh_bars: int,
) -> tuple[float | None, float, str]:
    """Return (value, threshold, kind), where kind is E for breakout or D for ST."""
    a = float(atr)
    if not math.isfinite(a) or a <= 0:
        return None, d_max, "D"

    if ref == "breakout" and i < len(st_upper):
        flip = last_up_flip(direction, i, fresh_bars)
        if flip is not None:
            level = float(st_upper[flip])
            if math.isfinite(level) and level > 0:
                return (float(close) - level) / a, ext_max, "E"

    line = float(st)
    if not math.isfinite(line):
        return None, d_max, "D"
    return (float(close) - line) / a, d_max, "D"
