"""Shared synthetic fixtures (no network, no pandas)."""

from __future__ import annotations

from datetime import datetime, timedelta

from supertrend_ema100.config import BacktestConfig
from supertrend_ema100.data.loader import LoadedData
from supertrend_ema100.data.series import SymbolSeries, build_series
from supertrend_ema100.kiwoom.models import Bar, DailyBar, StockInfo


def make_bars(
    day: str,
    prices: list[float],
    start_minute: int = 9 * 60 + 1,
    volume: float = 1_000.0,
    n_ticks: float | None = None,
    high_pad: float = 0.1,
    low_pad: float = 0.1,
) -> list[Bar]:
    bars: list[Bar] = []
    for offset, price in enumerate(prices):
        minute = start_minute + offset
        hhmm = f"{minute // 60:02d}{minute % 60:02d}"
        ticks = float(n_ticks) if n_ticks is not None else None
        bars.append(
            Bar(
                ts=day + hhmm,
                open=price,
                high=price + high_pad,
                low=price - low_pad,
                close=price,
                volume=volume,
                value=price * volume,
                n_ticks=ticks,
                buy_vol=volume * 0.5 if ticks is not None else None,
                sell_vol=volume * 0.5 if ticks is not None else None,
                path_len=0.2 if ticks is not None else None,
            )
        )
    return bars


def previous_day(day: str) -> str:
    current = datetime.strptime(day, "%Y%m%d")
    return (current - timedelta(days=1)).strftime("%Y%m%d")


def base_config(symbol: str = "005930") -> BacktestConfig:
    cfg = BacktestConfig()
    cfg.data.symbols = [symbol]
    cfg.data.feature_mode = "bar"
    cfg.confirm.use_value = False
    cfg.confirm.use_vwap = False
    cfg.confirm.use_rti = False
    cfg.confirm.use_buy_ratio = False
    cfg.confirm.use_rsi = False
    cfg.confirm.use_score = False
    cfg.score.enabled = False
    cfg.exits.trail_enabled = False
    cfg.exits.eod_exit = "15:15"
    cfg.exits.last_entry_time = "15:10"
    cfg.risk.slip_ticks = 1
    cfg.risk.max_positions = 3
    return cfg


def build_synthetic(
    cfg: BacktestConfig,
    day1: str = "20260102",
    day2: str = "20260105",
    prices: list[float] | None = None,
) -> tuple[SymbolSeries, LoadedData]:
    prices = prices or [100.0] * 12
    bars = make_bars(day1, prices) + make_bars(day2, prices)
    daily = [
        DailyBar(
            date=previous_day(day1),
            open=prices[0],
            high=prices[0],
            low=prices[0],
            close=prices[0],
            volume=1_000.0,
            value=prices[0] * 1_000.0,
        ),
        DailyBar(
            date=day1,
            open=prices[0],
            high=prices[0],
            low=prices[0],
            close=prices[0],
            volume=1_000.0,
            value=prices[0] * 1_000.0,
        ),
        DailyBar(
            date=day2,
            open=prices[0],
            high=prices[0],
            low=prices[0],
            close=prices[0],
            volume=1_000.0,
            value=prices[0] * 1_000.0,
        ),
    ]
    info = StockInfo(code=cfg.data.symbols[0], name="테스트", shares=1_000_000.0)
    series = build_series(info, bars, daily, {}, cfg)
    data = LoadedData(
        series={series.code: series},
        trading_dates=[day1, day2],
        start_date=day1,
        end_date=day2,
        feature_modes={series.code: series.feature_mode},
    )
    return series, data


def force_trigger(series: SymbolSeries, signal_index: int) -> None:
    """Make ``signal_index`` the only T1 bar: C(signal-1) false, C(signal) true."""
    for i in range(len(series.bars)):
        series.ready[i] = True
        series.direction[i] = 1
        series.st[i] = 100.0
        series.ema[i] = 99.0
    series.st[signal_index] = 99.95
    series.ema[signal_index] = 99.0
    if signal_index >= 1:
        series.direction[signal_index - 1] = -1
        series.st[signal_index - 1] = 98.0
        series.ema[signal_index - 1] = 99.0
