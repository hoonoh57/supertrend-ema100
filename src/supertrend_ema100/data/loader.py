"""Fetch, filter, resample and assemble the backtest inputs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable

from ..config import BacktestConfig
from ..indicators.tick_strength import BaselineBuilder
from ..kiwoom.client import KiwoomClient
from ..kiwoom.models import Bar, DailyBar, StockInfo
from .cache import BarCache
from .series import SymbolSeries, build_series
from .universe import load_universe

LogFn = Callable[[str], None]


def _log_noop(message: str) -> None:
    return


def ymd(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    return "".join(ch for ch in str(value) if ch.isdigit())[:8]


def parse_date(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"날짜 형식이 잘못되었습니다: {value} (YYYY-MM-DD 또는 YYYYMMDD)")


def hhmm_to_minutes(value: str) -> int:
    text = "".join(ch for ch in str(value) if ch.isdigit()).zfill(4)
    return int(text[:2]) * 60 + int(text[2:4])


def filter_session(
    bars: Iterable[Bar], start_hhmm: str, end_hhmm: str, include_nxt: bool = False
) -> list[Bar]:
    if include_nxt:
        return sorted((b for b in bars if b.day), key=lambda b: b.ts)
    start = hhmm_to_minutes(start_hhmm)
    end = hhmm_to_minutes(end_hhmm)
    out = [b for b in bars if start <= b.minute_of_day <= end]
    return sorted(out, key=lambda b: b.ts)


def resample_bars(bars: list[Bar], interval: int) -> list[Bar]:
    interval = max(1, int(interval))
    if interval == 1:
        return bars
    buckets: dict[str, list[Bar]] = {}
    for bar in bars:
        minute = bar.minute_of_day
        bucket_minute = int(math.ceil(minute / interval) * interval)
        if bucket_minute >= 24 * 60:
            bucket_minute = 24 * 60 - 1
        key = bar.day + f"{bucket_minute // 60:02d}{bucket_minute % 60:02d}"
        buckets.setdefault(key, []).append(bar)

    out: list[Bar] = []
    for key in sorted(buckets):
        group = buckets[key]
        tick_ok = all(b.has_tick_fields for b in group)
        n_ticks = sum(float(b.n_ticks) for b in group) if tick_ok else None
        buy = sum(float(b.buy_vol) for b in group) if tick_ok else None
        sell = sum(float(b.sell_vol) for b in group) if tick_ok else None
        path = (
            sum(float(b.path_len or 0.0) for b in group) if tick_ok else None
        )
        out.append(
            Bar(
                ts=key,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
                value=sum(b.value for b in group),
                n_ticks=n_ticks,
                buy_vol=buy,
                sell_vol=sell,
                path_len=path,
                p_first=group[0].p_first if tick_ok else None,
                p_last=group[-1].p_last if tick_ok else None,
                vi_flag=any(b.vi_flag for b in group),
            )
        )
    return out


@dataclass
class LoadedData:
    series: dict[str, SymbolSeries]
    trading_dates: list[str]
    start_date: str
    end_date: str
    warnings: list[str] = field(default_factory=list)
    feature_modes: dict[str, str] = field(default_factory=dict)


def _union_dates(daily_by_symbol: dict[str, list[DailyBar]]) -> list[str]:
    dates: set[str] = set()
    for bars in daily_by_symbol.values():
        dates.update(b.date for b in bars)
    return sorted(dates)


def load_backtest_data(
    client: KiwoomClient,
    cache: BarCache,
    infos: list[StockInfo],
    cfg: BacktestConfig,
    progress: LogFn | None = None,
    force_refresh: bool = False,
) -> LoadedData:
    log = progress or _log_noop
    requested_end = cfg.data.end or datetime.now().strftime("%Y-%m-%d")
    end_dt = parse_date(requested_end)
    assert end_dt is not None
    requested_end_ymd = ymd(end_dt)

    # ---- daily history (also used to pick real trading days) -----------------
    daily_until = ymd(end_dt - timedelta(days=500))
    daily_by_symbol: dict[str, list[DailyBar]] = {}
    for info in infos:
        log(f"[data] {info.name}({info.code}) 일봉 조회")
        daily_by_symbol[info.code] = cache.get_daily(
            client,
            info.code,
            end_date=requested_end_ymd,
            until_date=daily_until,
            force_refresh=force_refresh,
            progress=log,
        )

    trading_dates = _union_dates(daily_by_symbol)
    if not trading_dates:
        raise RuntimeError(
            "일봉 데이터를 받지 못했습니다. 키움 서버/종목코드/.env 인증을 확인하세요."
        )
    trading_dates = [d for d in trading_dates if d <= requested_end_ymd]
    if not trading_dates:
        raise RuntimeError("요청 기간에 해당하는 거래일이 없습니다.")
    effective_end = trading_dates[-1]

    # ---- choose the backtest window -----------------------------------------
    if cfg.data.start:
        wanted_start = ymd(parse_date(cfg.data.start))
        index = next((i for i, d in enumerate(trading_dates) if d >= wanted_start), None)
        if index is None:
            raise RuntimeError(f"시작일 {cfg.data.start} 이후 거래일이 없습니다.")
    else:
        index = max(0, len(trading_dates) - max(1, cfg.data.days))
    start_date = trading_dates[index]

    warmup_trading_days = max(cfg.baseline.base_days + 10, 30)
    warmup_index = max(0, index - warmup_trading_days)
    fetch_start = trading_dates[warmup_index]

    log(
        f"[data] 거래일 {len(trading_dates)}일 · 백테스트 {start_date}~{effective_end} "
        f"· 워밍업 시작 {fetch_start}"
    )

    # ---- minute bars ---------------------------------------------------------
    bars_by_symbol: dict[str, list[Bar]] = {}
    kept_infos: list[StockInfo] = []
    warned: list[str] = []
    for info in infos:
        daily = daily_by_symbol.get(info.code, [])
        if not daily:
            warned.append(f"{info.name}({info.code}): 일봉 없음")
            continue
        log(f"[data] {info.name}({info.code}) 분봉 조회 (캐시 우선)")
        bars = cache.get_minutes(
            client,
            info.code,
            end_date=effective_end,
            until_date=fetch_start,
            interval=1,
            force_refresh=force_refresh,
            progress=log if cfg.verbose else None,
        )
        if not bars:
            warned.append(f"{info.name}({info.code}): 분봉 없음")
            continue
        bars = filter_session(
            bars,
            cfg.data.session_start,
            cfg.data.session_end,
            cfg.data.include_nxt,
        )
        bars = resample_bars(bars, cfg.data.bar_interval)
        if not bars:
            warned.append(f"{info.name}({info.code}): 정규장 봉 없음")
            continue
        bars_by_symbol[info.code] = bars
        kept_infos.append(info)

    if not bars_by_symbol:
        raise RuntimeError("정규장 분봉이 있는 종목이 없습니다: " + "; ".join(warned))

    # ---- baselines (prior days only) ----------------------------------------
    listing_dates = {info.code: info.reg_day for info in kept_infos}
    baseline_builder = BaselineBuilder(
        bars_by_symbol,
        cfg.baseline,
        listing_dates=listing_dates,
        assumed_trade_size=cfg.data.assumed_trade_size,
    )
    baselines = baseline_builder.build_all()

    series: dict[str, SymbolSeries] = {}
    feature_modes: dict[str, str] = {}
    for info in kept_infos:
        try:
            s = build_series(
                info,
                bars_by_symbol[info.code],
                daily_by_symbol.get(info.code, []),
                baselines.get(info.code, {}),
                cfg,
            )
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not kill the run
            warned.append(f"{info.name}({info.code}): 지표 계산 실패 - {exc}")
            continue
        series[info.code] = s
        feature_modes[info.code] = s.feature_mode

    if not series:
        raise RuntimeError("지표 계산에 성공한 종목이 없습니다: " + "; ".join(warned))

    if cfg.universe.file:
        universe = load_universe(
            cfg.universe.file, cfg.universe.capture_from, cfg.universe.capture_to
        )
        for code, symbol_series in series.items():
            symbol_series.capture = universe.get(code, {})

    return LoadedData(
        series=series,
        trading_dates=trading_dates,
        start_date=start_date,
        end_date=effective_end,
        warnings=warned,
        feature_modes=feature_modes,
    )
