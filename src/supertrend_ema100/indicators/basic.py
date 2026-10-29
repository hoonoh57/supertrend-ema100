"""Indicator cores.

The SuperTrend / JMA / VWAP implementations follow the Kiwoom chart formula
engine where it is well defined (Wilder ATR, ratcheting bands, banker's
rounding for JMA).  The plan's EMA/RSI/VWAP math is used on top of those bars.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ..kiwoom.models import Bar

# --------------------------------------------------------------------- ticks


def tick_size(price: float) -> int:
    """KRX tick size (2023 bracket, same as the chart's tickSize.ts)."""
    p = abs(float(price))
    if p < 2000:
        return 1
    if p < 5000:
        return 5
    if p < 20000:
        return 10
    if p < 50000:
        return 50
    if p < 200000:
        return 100
    if p < 500000:
        return 500
    return 1000


def round_to_tick(price: float) -> float:
    if not math.isfinite(price) or price <= 0:
        return 0.0
    step = tick_size(price)
    return round(price / step) * step


# ------------------------------------------------------------------- helpers


def sma(values: Sequence[float | None], window: int) -> list[float | None]:
    window = max(1, int(window))
    out: list[float | None] = [None] * len(values)
    total = 0.0
    count = 0
    queue: list[float] = []
    for i, value in enumerate(values):
        if value is None or not math.isfinite(value):
            queue.append(float("nan"))
            total += float("nan")
        else:
            queue.append(float(value))
            total += float(value)
            count += 1
        if len(queue) > window:
            old = queue.pop(0)
            if math.isfinite(old):
                total -= old
                count -= 1
        if len(queue) == window and count == window:
            out[i] = total / window
    return out


def rolling_sum(values: Sequence[float | None], window: int) -> list[float | None]:
    window = max(1, int(window))
    out: list[float | None] = [None] * len(values)
    total = 0.0
    bad = 0
    queue: list[float | None] = []
    for i, value in enumerate(values):
        queue.append(value)
        if value is None or not math.isfinite(float(value)):
            bad += 1
        else:
            total += float(value)
        if len(queue) > window:
            old = queue.pop(0)
            if old is None or not math.isfinite(float(old)):
                bad -= 1
            else:
                total -= float(old)
        if len(queue) == window and bad == 0:
            out[i] = total
    return out


def rolling_max(values: Sequence[float | None], window: int) -> list[float | None]:
    window = max(1, int(window))
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if i + 1 < window:
            continue
        chunk = values[i - window + 1 : i + 1]
        if any(v is None or not math.isfinite(float(v)) for v in chunk):
            continue
        out[i] = max(float(v) for v in chunk)  # type: ignore[arg-type]
    return out


def rolling_min(values: Sequence[float | None], window: int) -> list[float | None]:
    window = max(1, int(window))
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if i + 1 < window:
            continue
        chunk = values[i - window + 1 : i + 1]
        if any(v is None or not math.isfinite(float(v)) for v in chunk):
            continue
        out[i] = min(float(v) for v in chunk)  # type: ignore[arg-type]
    return out


def median(values: Sequence[float]) -> float:
    data = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not data:
        return float("nan")
    n = len(data)
    if n % 2:
        return data[n // 2]
    return (data[n // 2 - 1] + data[n // 2]) / 2.0


# --------------------------------------------------------------------- ATR


def true_range(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(max(0.0, bar.high - bar.low))
        else:
            prev_close = bars[i - 1].close
            out.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prev_close),
                    abs(bar.low - prev_close),
                )
            )
    return out


def atr_wilder(bars: Sequence[Bar], length: int = 14, seed: str = "sma") -> list[float]:
    """Wilder ATR.  seed='sma' matches the Kiwoom chart engine."""
    n = max(1, int(length))
    tr = true_range(bars)
    out: list[float] = [0.0] * len(tr)
    if not tr:
        return out
    if seed == "sma":
        running = 0.0
        for i in range(len(tr)):
            if i < n:
                running += tr[i]
                out[i] = running / (i + 1)
            else:
                out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    else:
        out[0] = tr[0]
        for i in range(1, len(tr)):
            out[i] = out[i - 1] + (tr[i] - out[i - 1]) / n
    return out


# --------------------------------------------------------------------- EMA


def ema(values: Sequence[float], length: int) -> list[float]:
    n = max(1, int(length))
    if not values:
        return []
    alpha = 2.0 / (n + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1 - alpha) * out[-1])
    return out


# --------------------------------------------------------------- SuperTrend


@dataclass(slots=True)
class SuperTrendResult:
    atr: list[float]
    upper: list[float]
    lower: list[float]
    direction: list[int]
    st: list[float]
    ready: list[bool]


def supertrend(
    bars: Sequence[Bar], length: int = 14, multiplier: float = 2.0
) -> SuperTrendResult:
    """Kiwoom formula-parser compatible SuperTrend."""
    n = len(bars)
    atr = atr_wilder(bars, length, seed="sma")
    basic_upper = [0.0] * n
    basic_lower = [0.0] * n
    final_upper = [0.0] * n
    final_lower = [0.0] * n
    direction = [1] * n
    st = [0.0] * n
    ready = [False] * n
    if n == 0:
        return SuperTrendResult(atr, final_upper, final_lower, direction, st, ready)

    for i, bar in enumerate(bars):
        hl2 = (bar.high + bar.low) / 2.0
        basic_upper[i] = hl2 + multiplier * atr[i]
        basic_lower[i] = hl2 - multiplier * atr[i]
        ready[i] = i >= max(1, int(length)) - 1

    final_upper[0] = basic_upper[0]
    final_lower[0] = basic_lower[0]
    st[0] = basic_lower[0]
    direction[0] = 1
    trend = 1
    for i in range(1, n):
        prev_upper = final_upper[i - 1]
        prev_lower = final_lower[i - 1]
        prev_close = bars[i - 1].close
        close = bars[i].close
        final_upper[i] = (
            basic_upper[i]
            if (basic_upper[i] < prev_upper or prev_close > prev_upper)
            else prev_upper
        )
        final_lower[i] = (
            basic_lower[i]
            if (basic_lower[i] > prev_lower or prev_close < prev_lower)
            else prev_lower
        )
        if trend == 1:
            if close < final_lower[i]:
                trend = -1
                st[i] = final_upper[i]
            else:
                st[i] = final_lower[i]
        else:
            if close > final_upper[i]:
                trend = 1
                st[i] = final_lower[i]
            else:
                st[i] = final_upper[i]
        direction[i] = trend
    return SuperTrendResult(atr, final_upper, final_lower, direction, st, ready)


# --------------------------------------------------------------------- JMA


@dataclass(slots=True)
class JmaResult:
    values: list[float]
    direction: list[int]


def jma(
    values: Sequence[float],
    length: int = 7,
    phase: int = 50,
    power: int = 2,
) -> JmaResult:
    """Public Jurik-MA approximation used by the Kiwoom chart engine.

    * warm-up bars (count <= length) use the running arithmetic mean
    * after that, e2 + previous JMA, rounded half-even to 4 decimals
    """
    n = len(values)
    out = [0.0] * n
    direction = [1] * n
    if n == 0:
        return JmaResult(out, direction)
    length = max(1, int(length))
    power = max(1, int(power))
    phase = max(-100, min(100, int(phase)))
    phase_ratio = 0.5 if phase < -100 else (2.5 if phase > 100 else phase / 100.0 + 1.5)
    beta = (0.45 * (length - 1)) / (0.45 * (length - 1) + 2.0)
    alpha = beta**power

    e0 = e1 = e2 = 0.0
    last = float(values[0])
    warm_sum = 0.0
    count = 0
    prev_value = float(values[0])
    trend = 1
    for i, raw in enumerate(values):
        src = float(raw)
        if i == 0:
            e0, e1, e2 = src, 0.0, 0.0
            last = src
        count += 1
        warm_sum += src
        if i > 0:
            e0 = (1 - alpha) * src + alpha * e0
            e1 = (src - e0) * (1 - beta) + beta * e1
            e2 = (e0 + phase_ratio * e1 - last) * ((1 - alpha) ** 2) + (alpha**2) * e2
        current = (
            round(warm_sum / count, 4)
            if count <= length
            else round(e2 + last, 4)
        )
        if current > prev_value:
            trend = 1
        elif current < prev_value:
            trend = -1
        elif trend == 0:
            trend = 1
        out[i] = current
        direction[i] = trend
        last = current
        prev_value = current
    return JmaResult(out, direction)


# --------------------------------------------------------------------- RSI


def rsi(values: Sequence[float], length: int = 14, mode: str = "wilder") -> list[float | None]:
    n = max(1, int(length))
    out: list[float | None] = [None] * len(values)
    if len(values) <= 1:
        return out
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(values)):
        diff = float(values[i]) - float(values[i - 1])
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))

    if mode == "sma":
        for i in range(n, len(values)):
            avg_gain = sum(gains[i - n + 1 : i + 1]) / n
            avg_loss = sum(losses[i - n + 1 : i + 1]) / n
            out[i] = _rsi_value(avg_gain, avg_loss)
        return out

    avg_gain = sum(gains[1 : n + 1]) / n
    avg_loss = sum(losses[1 : n + 1]) / n
    for i in range(1, len(values)):
        if i < n:
            continue
        if i > n:
            avg_gain = (avg_gain * (n - 1) + gains[i]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# -------------------------------------------------------------------- VWAP


@dataclass(slots=True)
class VwapResult:
    vwap: list[float | None]
    sigma: list[float | None]
    sigma_eff: list[float | None]


def session_vwap(bars: Sequence[Bar], sigma_floor_pct: float = 0.003) -> VwapResult:
    """Bar-based session VWAP with weighted standard deviation.

    Resets on every exchange date; uses typical price (H+L+C)/3.
    """
    n = len(bars)
    vwap: list[float | None] = [None] * n
    sigma: list[float | None] = [None] * n
    sigma_eff: list[float | None] = [None] * n
    day = ""
    pv = 0.0
    vol = 0.0
    p2v = 0.0
    for i, bar in enumerate(bars):
        if bar.day != day:
            day = bar.day
            pv = vol = p2v = 0.0
        typical = (bar.high + bar.low + bar.close) / 3.0
        if bar.volume > 0 and math.isfinite(typical):
            pv += typical * bar.volume
            p2v += typical * typical * bar.volume
            vol += bar.volume
        if vol <= 0:
            continue
        value = pv / vol
        variance = max(0.0, p2v / vol - value * value)
        sd = math.sqrt(variance)
        vwap[i] = value
        sigma[i] = sd
        sigma_eff[i] = max(sd, sigma_floor_pct * value, 2.0 * tick_size(value))
    return VwapResult(vwap, sigma, sigma_eff)
