"""Tick-strength features and night-batch baselines (plan section 3).

Two feed modes are supported:

* ``tick`` - bars carry real per-minute trade counts, signed volume and path
  length (built from a tick file / live collector).
* ``bar``  - only OHLCV is available (the Kiwoom REST minute chart).  RTI then
  uses relative volume as the trade-frequency proxy, buy_ratio uses the close
  location value, ER uses bar ranges, and ATV is reported as unavailable.
  Every feature row records which mode was used, so a report never pretends a
  volume proxy is an exchange tick count.

Baselines always use days strictly before the evaluated day (no look-ahead).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..config import BaselineConfig
from ..kiwoom.models import Bar
from .basic import median, tick_size

MINUTES_PER_DAY = 24 * 60


@dataclass(slots=True)
class BaselineCurve:
    ticks: list[float]
    vpt: list[float]
    n_days: int
    fallback: bool
    ready: bool


@dataclass(slots=True)
class TickFeatures:
    n_ticks: list[float | None]
    base_ticks: list[float | None]
    base_vpt: list[float | None]
    rti_1: list[float | None]
    rti_3: list[float | None]
    rti_10: list[float | None]
    accel: list[float | None]
    buy_ratio_5: list[float | None]
    er_5: list[float | None]
    atv_ratio_5: list[float | None]
    tov_5: list[float | None]
    path_len: list[float | None]
    buy_vol: list[float | None]
    sell_vol: list[float | None]
    baseline_ready: list[bool]
    feature_mode: str


def _nan() -> float:
    return float("nan")


def _is_finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _smooth_curve(curve: list[float], window: int) -> list[float]:
    """Centered moving average over available minutes."""
    if window <= 0:
        return list(curve)
    out = [_nan()] * MINUTES_PER_DAY
    for m in range(MINUTES_PER_DAY):
        lo = max(0, m - window)
        hi = min(MINUTES_PER_DAY, m + window + 1)
        values = [curve[j] for j in range(lo, hi) if _is_finite(curve[j])]
        if values:
            out[m] = sum(values) / len(values)
    return out


def _mean(values: Sequence[float]) -> float:
    finite = [float(v) for v in values if _is_finite(v)]
    return sum(finite) / len(finite) if finite else _nan()


class BaselineBuilder:
    """Per-symbol, per-day minute baselines from prior sessions only."""

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]],
        config: BaselineConfig,
        listing_dates: dict[str, str] | None = None,
        assumed_trade_size: float = 1.0,
    ) -> None:
        self.cfg = config
        self.listing_dates = listing_dates or {}
        self.assumed_trade_size = max(float(assumed_trade_size), 1e-9)
        self.symbols = list(bars_by_symbol)
        self.days: dict[str, list[str]] = {}
        self.day_ticks: dict[str, dict[str, list[float]]] = {}
        self.day_vpt: dict[str, dict[str, list[float]]] = {}
        self.day_count: dict[str, dict[str, int]] = {}
        self.day_avg_ticks: dict[str, dict[str, float]] = {}
        self._smoothed_ticks: dict[tuple[str, str], list[float]] = {}
        self._smoothed_vpt: dict[tuple[str, str], list[float]] = {}
        self._profile_cache: dict[str, dict[int, float]] = {}

        for symbol, bars in bars_by_symbol.items():
            per_day_ticks: dict[str, list[float]] = {}
            per_day_vpt: dict[str, list[float]] = {}
            per_day_count: dict[str, int] = {}
            for bar in bars:
                day = bar.day
                minute = bar.minute_of_day
                ticks = bar.n_ticks if bar.n_ticks is not None else (
                    bar.volume / self.assumed_trade_size
                )
                if ticks < 0:
                    ticks = 0.0
                if day not in per_day_ticks:
                    per_day_ticks[day] = [_nan()] * MINUTES_PER_DAY
                    per_day_vpt[day] = [_nan()] * MINUTES_PER_DAY
                    per_day_count[day] = 0
                per_day_ticks[day][minute] = float(ticks)
                vpt = bar.value / ticks if ticks > 0 else _nan()
                per_day_vpt[day][minute] = vpt
                per_day_count[day] += 1
            self.days[symbol] = sorted(per_day_ticks)
            self.day_ticks[symbol] = per_day_ticks
            self.day_vpt[symbol] = per_day_vpt
            self.day_count[symbol] = per_day_count
            self.day_avg_ticks[symbol] = {
                day: _mean(per_day_ticks[day]) for day in per_day_ticks
            }

    def _valid_day(self, symbol: str, day: str) -> bool:
        if self.day_count[symbol].get(day, 0) < self.cfg.min_bars_per_day:
            return False
        reg = self.listing_dates.get(symbol, "")
        if reg and len(reg) == 8:
            try:
                listed = datetime.strptime(reg, "%Y%m%d")
                current = datetime.strptime(day, "%Y%m%d")
                if (current - listed).days <= self.cfg.ipo_exclude_days:
                    return False
            except ValueError:
                pass
        return True

    def _prior_days(self, symbol: str, day: str) -> list[str]:
        days = [d for d in self.days.get(symbol, []) if d < day]
        valid = [d for d in days if self._valid_day(symbol, d)]
        return valid[-max(1, self.cfg.base_days) :]

    def _smoothed(self, symbol: str, day: str) -> tuple[list[float], list[float]]:
        key = (symbol, day)
        if key not in self._smoothed_ticks:
            self._smoothed_ticks[key] = _smooth_curve(
                self.day_ticks[symbol][day], self.cfg.base_smooth
            )
            self._smoothed_vpt[key] = _smooth_curve(
                self.day_vpt[symbol][day], self.cfg.base_smooth
            )
        return self._smoothed_ticks[key], self._smoothed_vpt[key]

    def market_profile(self, day: str) -> dict[int, float]:
        """Cross-sectional intraday shape from all symbols' prior days."""
        if day in self._profile_cache:
            return self._profile_cache[day]
        values: dict[int, list[float]] = defaultdict(list)
        for symbol in self.symbols:
            for prior in self._prior_days(symbol, day):
                avg = self.day_avg_ticks[symbol].get(prior, _nan())
                if not _is_finite(avg) or avg <= 0:
                    continue
                curve, _ = self._smoothed(symbol, prior)
                for m in range(MINUTES_PER_DAY):
                    if _is_finite(curve[m]):
                        values[m].append(curve[m] / avg)
        profile = {m: median(vals) if vals else 1.0 for m, vals in values.items()}
        self._profile_cache[day] = profile
        return profile

    def build_curve(self, symbol: str, day: str) -> BaselineCurve:
        prior = self._prior_days(symbol, day)
        n_days = len(prior)
        ticks = [self.cfg.base_floor] * MINUTES_PER_DAY
        vpt = [_nan()] * MINUTES_PER_DAY
        if n_days == 0:
            return BaselineCurve(ticks, vpt, 0, True, False)

        if n_days >= self.cfg.base_min_days:
            smoothed = [self._smoothed(symbol, d) for d in prior]
            for m in range(MINUTES_PER_DAY):
                tick_values = [pair[0][m] for pair in smoothed if _is_finite(pair[0][m])]
                vpt_values = [pair[1][m] for pair in smoothed if _is_finite(pair[1][m])]
                if tick_values:
                    ticks[m] = max(self.cfg.base_floor, median(tick_values))
                if vpt_values:
                    vpt[m] = median(vpt_values)
            return BaselineCurve(ticks, vpt, n_days, False, True)

        # New listing / short history: use the market's intraday shape.
        profile = self.market_profile(day)
        avg_ticks = _mean(
            [self.day_avg_ticks[symbol].get(d, _nan()) for d in prior]
        )
        if not _is_finite(avg_ticks) or avg_ticks <= 0:
            return BaselineCurve(ticks, vpt, n_days, True, False)
        smoothed = [self._smoothed(symbol, d) for d in prior]
        for m in range(MINUTES_PER_DAY):
            ticks[m] = max(self.cfg.base_floor, avg_ticks * profile.get(m, 1.0))
            vpt_values = [pair[1][m] for pair in smoothed if _is_finite(pair[1][m])]
            if vpt_values:
                vpt[m] = median(vpt_values)
        if not any(_is_finite(v) for v in vpt):
            all_vpt = [
                self.day_vpt[symbol][d][m]
                for d in prior
                for m in range(MINUTES_PER_DAY)
                if _is_finite(self.day_vpt[symbol][d][m])
            ]
            avg_vpt = _mean(all_vpt)
            if _is_finite(avg_vpt):
                vpt = [avg_vpt] * MINUTES_PER_DAY
        return BaselineCurve(ticks, vpt, n_days, True, True)

    def build_all(self) -> dict[str, dict[str, BaselineCurve]]:
        result: dict[str, dict[str, BaselineCurve]] = {}
        for symbol in self.symbols:
            result[symbol] = {
                day: self.build_curve(symbol, day) for day in self.days[symbol]
            }
        return result


def _day_rolling_sum(
    values: Sequence[float | None], window: int, days: Sequence[str]
) -> list[float | None]:
    """Rolling sum that requires a complete window within one trading session."""
    n = len(values)
    window = max(1, int(window))
    out: list[float | None] = [None] * n
    for i in range(n):
        lo = i - window + 1
        if lo < 0 or days[lo] != days[i]:
            continue
        total = 0.0
        for j in range(lo, i + 1):
            value = values[j]
            if value is None or not math.isfinite(float(value)):
                break
            total += float(value)
        else:
            out[i] = total
    return out


def _proxy_buy_sell(bar: Bar) -> tuple[float, float]:
    span = bar.high - bar.low
    if span <= 0:
        frac = 0.5
    else:
        clv = ((bar.close - bar.low) - (bar.high - bar.close)) / span
        frac = max(0.0, min(1.0, (clv + 1.0) / 2.0))
    return bar.volume * frac, bar.volume * (1.0 - frac)


def compute_tick_features(
    bars: Sequence[Bar],
    baselines: dict[str, BaselineCurve],
    market_cap: float | Sequence[float],
    assumed_trade_size: float = 1.0,
    feature_mode: str = "auto",
) -> TickFeatures:
    n = len(bars)
    if isinstance(market_cap, (int, float)):
        caps = [float(market_cap)] * n
    else:
        caps = [float(v) for v in market_cap]
        if len(caps) != n:
            raise ValueError("market_cap must be a scalar or one value per bar")
    true_mode = bool(bars) and all(bar.has_tick_fields for bar in bars[: min(n, 20)])
    mode = "tick" if feature_mode == "tick" else ("tick" if feature_mode == "auto" and true_mode else "bar")
    use_true = mode == "tick" and true_mode

    n_ticks: list[float | None] = [None] * n
    base_ticks: list[float | None] = [None] * n
    base_vpt: list[float | None] = [None] * n
    path_len: list[float | None] = [None] * n
    buy_vol: list[float | None] = [None] * n
    sell_vol: list[float | None] = [None] * n
    baseline_ready = [False] * n

    for i, bar in enumerate(bars):
        curve = baselines.get(bar.day)
        minute = bar.minute_of_day
        if use_true:
            n_ticks[i] = float(bar.n_ticks or 0.0)
            buy_vol[i] = float(bar.buy_vol or 0.0)
            sell_vol[i] = float(bar.sell_vol or 0.0)
            path_len[i] = float(bar.path_len or max(0.0, bar.high - bar.low))
        else:
            n_ticks[i] = max(0.0, float(bar.volume) / max(assumed_trade_size, 1e-9))
            bv, sv = _proxy_buy_sell(bar)
            buy_vol[i] = bv
            sell_vol[i] = sv
            path_len[i] = max(0.0, bar.high - bar.low)
        if curve and curve.ready:
            base_ticks[i] = curve.ticks[minute]
            base_vpt[i] = curve.vpt[minute] if _is_finite(curve.vpt[minute]) else None
            baseline_ready[i] = True

    days = [bar.day for bar in bars]

    def window_sum(values: list[float | None], window: int) -> list[float | None]:
        return _day_rolling_sum(values, window, days)

    sum_ticks_1 = window_sum(n_ticks, 1)
    sum_ticks_3 = window_sum(n_ticks, 3)
    sum_ticks_10 = window_sum(n_ticks, 10)
    sum_base_1 = window_sum(base_ticks, 1)
    sum_base_3 = window_sum(base_ticks, 3)
    sum_base_10 = window_sum(base_ticks, 10)
    sum_buy = window_sum(buy_vol, 5)
    sum_sell = window_sum(sell_vol, 5)
    sum_value = window_sum([bar.value for bar in bars], 5)
    sum_path = window_sum(path_len, 5)
    sum_n = window_sum(n_ticks, 5)
    sum_base_vpt = window_sum(base_vpt, 5)

    def ratio(num: list[float | None], den: list[float | None], i: int) -> float | None:
        a, b = num[i], den[i]
        if a is None or b is None or not _is_finite(b) or b <= 0:
            return None
        return float(a) / float(b)

    rti_1 = [ratio(sum_ticks_1, sum_base_1, i) for i in range(n)]
    rti_3 = [ratio(sum_ticks_3, sum_base_3, i) for i in range(n)]
    rti_10 = [ratio(sum_ticks_10, sum_base_10, i) for i in range(n)]
    accel = [
        (rti_1[i] / rti_10[i])
        if rti_1[i] is not None and rti_10[i] not in (None, 0.0)
        else None
        for i in range(n)
    ]

    buy_ratio_5: list[float | None] = [None] * n
    for i in range(n):
        b, s = sum_buy[i], sum_sell[i]
        if b is None or s is None or (b + s) <= 0:
            continue
        buy_ratio_5[i] = b / (b + s)

    er_5: list[float | None] = [None] * n
    for i in range(4, n):
        if bars[i - 4].day != bars[i].day:
            continue
        den = sum_path[i]
        if den is None or den <= 0:
            continue
        first_price = bars[i - 4].open
        er_5[i] = (bars[i].close - first_price) / den

    atv_ratio_5: list[float | None] = [None] * n
    if use_true:
        for i in range(n):
            value_sum, tick_sum, vpt_sum = sum_value[i], sum_n[i], sum_base_vpt[i]
            if not value_sum or not tick_sum or not vpt_sum or tick_sum <= 0 or vpt_sum <= 0:
                continue
            atv_ratio_5[i] = (value_sum / tick_sum) / (vpt_sum / 5.0)

    tov_5: list[float | None] = [None] * n
    for i in range(n):
        value_sum = sum_value[i]
        cap = caps[i] if i < len(caps) else 0.0
        if value_sum is None or cap <= 0:
            continue
        tov_5[i] = value_sum / cap * 10_000.0 / 5.0

    # VI contamination: a VI minute inside the rolling window invalidates it.
    for i in range(n):
        day = bars[i].day
        if any(
            bars[j].vi_flag and bars[j].day == day
            for j in range(max(0, i - 9), i + 1)
        ):
            rti_1[i] = rti_3[i] = rti_10[i] = None
            accel[i] = buy_ratio_5[i] = er_5[i] = atv_ratio_5[i] = None
        if any(
            bars[j].vi_flag and bars[j].day == day
            for j in range(max(0, i - 4), i + 1)
        ):
            buy_ratio_5[i] = er_5[i] = atv_ratio_5[i] = None

    return TickFeatures(
        n_ticks=n_ticks,
        base_ticks=base_ticks,
        base_vpt=base_vpt,
        rti_1=rti_1,
        rti_3=rti_3,
        rti_10=rti_10,
        accel=accel,
        buy_ratio_5=buy_ratio_5,
        er_5=er_5,
        atv_ratio_5=atv_ratio_5,
        tov_5=tov_5,
        path_len=path_len,
        buy_vol=buy_vol,
        sell_vol=sell_vol,
        baseline_ready=baseline_ready,
        feature_mode=mode,
    )
