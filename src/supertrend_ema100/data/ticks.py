"""Aggregate raw trade ticks into 1-minute bars (plan 1.1 - 1.3).

The REST chart API does not expose per-tick counts or signed volume, so this
module is the bridge used by a live collector (or an imported tick file) to
produce bars that carry the real tick fields.  Sign inference follows the plan:
price up -> +, down -> -, unchanged -> carry the previous sign.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..kiwoom.models import Bar, Tick


@dataclass(slots=True)
class TickBar:
    bar: Bar
    sign_changes: int


def _hhmm_minutes(value: str) -> int:
    text = "".join(ch for ch in str(value) if ch.isdigit()).zfill(4)
    return int(text[:2]) * 60 + int(text[2:4])


def build_bars_from_ticks(
    ticks: Iterable[Tick],
    *,
    session_start: str = "0901",
    session_end: str = "1520",
    vi_minutes: Sequence[str] | None = None,
) -> list[Bar]:
    """Build minute bars with n_ticks / buy_vol / sell_vol / path_len.

    ``vi_minutes`` is a list of ``YYYYMMDDHHMM`` keys (or ``HHMM``) whose bars
    should be flagged as VI-contaminated.
    """
    ordered = sorted(
        (t for t in ticks if t.price > 0 and t.ts and len(t.ts) >= 12),
        key=lambda t: t.ts,
    )
    if not ordered:
        return []

    start = _hhmm_minutes(session_start)
    end = _hhmm_minutes(session_end)
    vi_keys = {str(v) for v in (vi_minutes or [])}

    groups: dict[str, list[tuple[Tick, int]]] = {}
    prev_price: float | None = None
    sign = 1
    for tick in ordered:
        price = float(tick.price)
        if prev_price is not None:
            if price > prev_price:
                sign = 1
            elif price < prev_price:
                sign = -1
            # equal price keeps the previous sign (plan 1.1)
        prev_price = price

        minute = tick.ts[:12]
        minute_of_day = int(minute[8:10]) * 60 + int(minute[10:12])
        if minute_of_day < start or minute_of_day > end:
            # Still used for sign carry-over, but not counted.
            continue
        groups.setdefault(minute, []).append((tick, sign))

    bars: list[Bar] = []
    for minute in sorted(groups):
        rows = groups[minute]
        prices = [float(t.price) for t, _s in rows]
        volumes = [abs(float(t.volume)) for t, _s in rows]
        signed = [float(t.volume) * s for t, s in rows]
        path = 0.0
        for i in range(1, len(prices)):
            path += abs(prices[i] - prices[i - 1])
        buy = sum(v for v in signed if v > 0)
        sell = sum(-v for v in signed if v < 0)
        value = sum(p * v for p, v in zip(prices, volumes))
        hhmm = minute[8:12]
        bars.append(
            Bar(
                ts=minute,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum(volumes),
                value=value,
                n_ticks=float(len(rows)),
                buy_vol=buy,
                sell_vol=sell,
                path_len=path,
                p_first=prices[0],
                p_last=prices[-1],
                vi_flag=(minute in vi_keys) or (hhmm in vi_keys),
            )
        )
    return bars


def bar_duration_seconds(
    ticks: Iterable[Tick], minute_ts: str, target_ticks: int = 30
) -> float | None:
    """Time (seconds) needed to complete an N-tick bar (plan 3.2, monitoring)."""
    rows = sorted(
        (t for t in ticks if t.ts[:12] == minute_ts), key=lambda t: t.ts
    )
    if len(rows) < target_ticks or target_ticks <= 1:
        return None
    def seconds(ts: str) -> float:
        return int(ts[8:10]) * 3600 + int(ts[10:12]) * 60 + int(ts[12:14])

    span = seconds(rows[target_ticks - 1].ts) - seconds(rows[0].ts)
    return float(max(0, span))


def average_trade_value(bar: Bar) -> float | None:
    if not bar.n_ticks or bar.n_ticks <= 0 or not math.isfinite(bar.value):
        return None
    return bar.value / bar.n_ticks
