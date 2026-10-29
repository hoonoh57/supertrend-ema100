"""Delay filters, re-arm events and confirmation checks (plan 4.2 - 4.4)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import BacktestConfig
from ..data.series import SymbolSeries


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def day_blocked(series: SymbolSeries, i: int, cfg: BacktestConfig) -> bool:
    ret = series.day_ret[i]
    return ret is not None and ret >= cfg.delay.max_day_ret


def delay_reasons(
    series: SymbolSeries,
    i: int,
    cfg: BacktestConfig,
    *,
    check_gap: bool,
    gap_consumed: bool,
    vi_release_minute: int | None = None,
) -> list[str]:
    bar = series.bars[i]
    reasons: list[str] = []
    atr = series.atr[i]
    st = series.st[i]
    if atr > 0 and _finite(st):
        if (bar.close - st) / atr > cfg.delay.d_max:
            reasons.append("EXT")
    vi_up = series.vi_up[i]
    if _finite(vi_up) and bar.close > 0:
        if (float(vi_up) - bar.close) / bar.close < cfg.delay.vi_buffer_pct:
            reasons.append("VI")
    prev = series.prev_close[i]
    if _finite(prev) and float(prev) > 0:
        if bar.close >= float(prev) * (1.0 + cfg.delay.limit_zone_pct):
            reasons.append("LIMIT")
    if vi_release_minute is not None and cfg.delay.vi_cooldown_min > 0:
        if bar.minute_of_day - vi_release_minute < cfg.delay.vi_cooldown_min:
            reasons.append("VICOOL")
    # Recent bar return spike.
    if i >= 1:
        lookback = max(1, cfg.delay.bar_lookback)
        peak = 0.0
        for j in range(max(1, i - lookback + 1), i + 1):
            prev_close = series.bars[j - 1].close
            if prev_close > 0:
                peak = max(peak, series.bars[j].close / prev_close - 1.0)
        if peak >= cfg.delay.bar_ret_pct:
            reasons.append("BAR")
    if check_gap and series.gap_flag[i] and not gap_consumed:
        reasons.append("GAP")
    return reasons


def trig_state(series: SymbolSeries, i: int) -> bool:
    """C_t = dir=+1 and ST line above EMA100 (only after ATR warm-up)."""
    return (
        series.ready[i]
        and series.direction[i] == 1
        and series.st[i] > series.ema[i]
    )


def is_trigger(series: SymbolSeries, i: int) -> bool:
    if i < 1:
        return False
    return trig_state(series, i) and not trig_state(series, i - 1)


def _st_rearm(series: SymbolSeries, i: int, cfg: BacktestConfig) -> bool:
    if i < 1:
        return False
    if not (series.direction[i - 1] == -1 and series.direction[i] == 1):
        return False
    bar = series.bars[i]
    if bar.close <= series.ema[i]:
        return False
    if cfg.rearm.st_require_above_ema and series.st[i] <= series.ema[i]:
        return False
    return True


def _jma_rearm(series: SymbolSeries, i: int, cfg: BacktestConfig) -> bool:
    if i < 2:
        return False
    j = series.jma
    if not (j[i] > j[i - 1] and j[i - 1] <= j[i - 2]):
        return False
    # Count consecutive declining JMA bars ending at i-1.
    k = i - 1
    decline = 0
    while k >= 1 and j[k] < j[k - 1]:
        decline += 1
        k -= 1
    if decline < cfg.rearm.jma_min_down:
        return False
    bar = series.bars[i]
    if series.direction[i] != 1 or bar.close <= series.ema[i]:
        return False
    # Pullback depth: lowest low during the decline minus the ST line then.
    if i - 1 > k:
        depths = [
            series.bars[m].low - series.st[m]
            for m in range(k + 1, i)
            if math.isfinite(series.st[m])
        ]
        if not depths:
            return False
        if min(depths) > cfg.rearm.pb_atr * series.atr[i]:
            return False
    return True


def rearm_event(series: SymbolSeries, i: int, cfg: BacktestConfig) -> bool:
    mode = cfg.rearm.mode.upper()
    st_ok = _st_rearm(series, i, cfg)
    jma_ok = _jma_rearm(series, i, cfg)
    if mode == "ST":
        return st_ok
    if mode == "JMA":
        return jma_ok
    return st_ok or jma_ok


@dataclass(slots=True)
class ConfirmResult:
    passed: bool
    checks: dict[str, bool]

    def failed(self) -> list[str]:
        return [k for k, v in self.checks.items() if not v]


def confirm_checks(series: SymbolSeries, i: int, cfg: BacktestConfig) -> ConfirmResult:
    bar = series.bars[i]
    c = cfg.confirm
    checks: dict[str, bool] = {}
    if c.use_value:
        checks["K_VAL"] = bar.value >= c.min_bar_value
    if c.use_vwap:
        checks["K_VWAP"] = series.vwap[i] is not None and bar.close > float(series.vwap[i])
    if c.use_rti:
        rti = series.features.rti_3[i]
        checks["K_RTI"] = (
            series.features.baseline_ready[i]
            and rti is not None
            and rti >= c.min_rti
        )
    if c.use_buy_ratio:
        value = series.features.buy_ratio_5[i]
        checks["K_BUY"] = value is not None and value >= c.min_buy_ratio
    if c.use_rsi:
        value = series.rsi[i]
        checks["K_RSI"] = value is not None and c.rsi_lo <= float(value) <= c.rsi_hi
    if c.use_score:
        checks["K_SCORE"] = series.scores[i].score >= c.min_score
    return ConfirmResult(all(checks.values()), checks)
