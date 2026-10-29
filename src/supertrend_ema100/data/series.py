"""Assemble a continuous intraday series with all plan indicators/features."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Sequence

from ..config import BacktestConfig
from ..indicators.basic import (
    SuperTrendResult,
    ema,
    jma,
    round_to_tick,
    rsi,
    session_vwap,
    supertrend,
    tick_size,
)
from ..indicators.score import ScoreResult, compute_score
from ..indicators.tick_strength import BaselineCurve, TickFeatures, compute_tick_features
from ..kiwoom.models import Bar, DailyBar, StockInfo


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _pct(values: Sequence[float], p: float) -> float | None:
    data = sorted(float(v) for v in values if _finite(v))
    if len(data) < 20:
        return None
    index = (len(data) - 1) * p
    lo = int(math.floor(index))
    hi = int(math.ceil(index))
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (index - lo)


@dataclass(slots=True)
class SymbolSeries:
    info: StockInfo
    bars: list[Bar]
    daily: list[DailyBar]
    atr: list[float]
    ema: list[float]
    st: list[float]
    direction: list[int]
    ready: list[bool]
    jma: list[float]
    jma_dir: list[int]
    rsi: list[float | None]
    vwap: list[float | None]
    sigma_eff: list[float | None]
    features: TickFeatures
    scores: list[ScoreResult]
    prev_close: list[float | None]
    day_open: list[float | None]
    day_ret: list[float | None]
    vi_up: list[float | None]
    gap_flag: list[bool]
    above_vwap_ratio: list[float | None]
    vwap_slope_atr: list[float | None]
    tov_p50: list[float | None]
    tov_p95: list[float | None]
    market_cap: list[float]
    feature_mode: str
    index_by_ts: dict[str, int] = field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.info.code

    @property
    def name(self) -> str:
        return self.info.name or self.info.code

    def score_at(self, i: int) -> ScoreResult:
        return self.scores[i]

    def tick_size_at(self, i: int) -> int:
        return tick_size(self.bars[i].close)

    def day_indices(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for i, bar in enumerate(self.bars):
            out.setdefault(bar.day, []).append(i)
        return out

    def first_index_on_or_after(self, day: str) -> int:
        for i, bar in enumerate(self.bars):
            if bar.day >= day:
                return i
        return len(self.bars)


def _build_day_level(
    bars: Sequence[Bar],
    daily: Sequence[DailyBar],
    vi_static_pct: float = 0.10,
    gap_pct: float = 0.05,
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
    list[bool],
]:
    # The cache/client always return daily bars oldest-first, which bisect needs.
    daily_dates = sorted(d.date for d in daily)
    daily_close = {d.date: d.close for d in daily}
    daily_open = {d.date: d.open for d in daily}
    first_open: dict[str, float] = {}
    for bar in bars:
        first_open.setdefault(bar.day, bar.open)

    prev_close: list[float | None] = []
    day_open: list[float | None] = []
    day_ret: list[float | None] = []
    vi_up: list[float | None] = []
    gap_flag: list[bool] = []
    cache: dict[str, tuple[float | None, float | None]] = {}

    for bar in bars:
        day = bar.day
        if day not in cache:
            idx = bisect.bisect_left(daily_dates, day) - 1
            prev = daily_close.get(daily_dates[idx]) if idx >= 0 else None
            open_ = daily_open.get(day) or first_open.get(day)
            cache[day] = (prev, open_)
        prev, open_ = cache[day]
        prev_close.append(prev)
        day_open.append(open_)
        day_ret.append((bar.close / prev - 1.0) if prev and prev > 0 else None)
        vi_up.append(
            round_to_tick(open_ * (1.0 + vi_static_pct)) if open_ and open_ > 0 else None
        )
        gap_flag.append(
            bool(
                prev
                and open_
                and prev > 0
                and (open_ / prev - 1.0) >= gap_pct
            )
        )
    return prev_close, day_open, day_ret, vi_up, gap_flag


def _above_vwap_ratio(
    bars: Sequence[Bar], vwap: Sequence[float | None], window: int = 30
) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        lo = max(0, i - window + 1)
        count = 0
        total = 0
        for j in range(lo, i + 1):
            if vwap[j] is None:
                continue
            total += 1
            if bars[j].close > float(vwap[j]):
                count += 1
        if total >= max(10, window // 3):
            out[i] = count / total
    return out


def _tov_percentiles(
    bars: Sequence[Bar],
    features: TickFeatures,
    base_days: int = 20,
) -> tuple[list[float | None], list[float | None]]:
    by_day: dict[str, list[float]] = {}
    for i, bar in enumerate(bars):
        value = features.tov_5[i]
        if value is not None and math.isfinite(value):
            by_day.setdefault(bar.day, []).append(value)
    days = sorted(by_day)
    p50: list[float | None] = [None] * len(bars)
    p95: list[float | None] = [None] * len(bars)
    day_values: dict[str, tuple[float | None, float | None]] = {}
    for day in days:
        prior = [d for d in days if d < day][-max(1, base_days) :]
        values = [v for d in prior for v in by_day[d]]
        day_values[day] = (_pct(values, 0.50), _pct(values, 0.95))
    for i, bar in enumerate(bars):
        p50[i], p95[i] = day_values.get(bar.day, (None, None))
    return p50, p95


def build_series(
    info: StockInfo,
    bars: list[Bar],
    daily: list[DailyBar],
    baseline_curves: dict[str, BaselineCurve],
    cfg: BacktestConfig,
) -> SymbolSeries:
    if not bars:
        raise ValueError(f"{info.code} 분봉이 없습니다.")
    bars = sorted(bars, key=lambda b: b.ts)
    closes = [b.close for b in bars]

    st_result: SuperTrendResult = supertrend(
        bars, cfg.indicators.atr_len, cfg.indicators.st_mult
    )
    ema_values = ema(closes, cfg.indicators.ema_len)
    jma_result = jma(
        closes,
        cfg.indicators.jma_len,
        cfg.indicators.jma_phase,
        cfg.indicators.jma_power,
    )
    rsi_values = rsi(closes, cfg.indicators.rsi_len, cfg.indicators.rsi_mode)
    vwap_result = session_vwap(bars, cfg.indicators.vwap_sigma_floor_pct)

    prev_close, day_open, day_ret, vi_up, gap_flag = _build_day_level(
        bars,
        daily,
        vi_static_pct=cfg.delay.vi_static_pct,
        gap_pct=cfg.delay.gap_pct,
    )
    shares = info.shares or 0.0
    market_cap = [
        shares * prev if prev and prev > 0 else 0.0 for prev in prev_close
    ]
    features = compute_tick_features(
        bars,
        baseline_curves,
        market_cap=market_cap,
        assumed_trade_size=cfg.data.assumed_trade_size,
        feature_mode=cfg.data.feature_mode,
    )

    above = _above_vwap_ratio(bars, vwap_result.vwap, 30)
    slope: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if i >= 10 and vwap_result.vwap[i] is not None and vwap_result.vwap[i - 10] is not None:
            atr = st_result.atr[i]
            if atr > 0:
                slope[i] = (float(vwap_result.vwap[i]) - float(vwap_result.vwap[i - 10])) / atr

    tov_p50, tov_p95 = _tov_percentiles(bars, features, cfg.baseline.base_days)

    scores: list[ScoreResult] = []
    for i, bar in enumerate(bars):
        scores.append(
            compute_score(
                cfg.score,
                close=bar.close,
                vwap=vwap_result.vwap[i],
                sigma_eff=vwap_result.sigma_eff[i],
                vwap_slope_atr=slope[i],
                above_vwap_ratio=above[i],
                rti_3=features.rti_3[i],
                accel=features.accel[i],
                buy_ratio=features.buy_ratio_5[i],
                er_tick=features.er_5[i],
                atv_ratio=features.atv_ratio_5[i],
                tov=features.tov_5[i],
                tov_p50=tov_p50[i],
                tov_p95=tov_p95[i],
                st_line=st_result.st[i] if st_result.ready[i] else None,
                atr=st_result.atr[i] if st_result.ready[i] else None,
                vi_up=vi_up[i],
                grade_multipliers=cfg.risk.grade_multipliers,
            )
        )

    series = SymbolSeries(
        info=info,
        bars=bars,
        daily=list(daily),
        atr=st_result.atr,
        ema=ema_values,
        st=st_result.st,
        direction=st_result.direction,
        ready=st_result.ready,
        jma=jma_result.values,
        jma_dir=jma_result.direction,
        rsi=rsi_values,
        vwap=vwap_result.vwap,
        sigma_eff=vwap_result.sigma_eff,
        features=features,
        scores=scores,
        prev_close=prev_close,
        day_open=day_open,
        day_ret=day_ret,
        vi_up=vi_up,
        gap_flag=gap_flag,
        above_vwap_ratio=above,
        vwap_slope_atr=slope,
        tov_p50=tov_p50,
        tov_p95=tov_p95,
        market_cap=market_cap,
        feature_mode=features.feature_mode,
    )
    series.index_by_ts = {b.ts: i for i, b in enumerate(bars)}
    return series
