"""Configuration objects for the Supertrend-EMA100 backtest engine.

Every threshold from plan.txt is a field here.  A JSON file can override any
subset of them; unknown keys are rejected so a typo never silently changes a
backtest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def _coerce(value: Any, default: Any) -> Any:
    """Coerce a JSON scalar to the type of its dataclass default."""
    if value is None:
        return None
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    if isinstance(default, tuple):
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value
    return value


def _apply_dict(obj: Any, data: dict[str, Any], prefix: str = "") -> Any:
    known = {f.name: f for f in fields(obj)}
    for key, raw in data.items():
        if key not in known:
            raise ValueError(f"Unknown config key: {prefix}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(raw, dict):
                raise ValueError(f"Config key {prefix}{key} must be an object")
            _apply_dict(current, raw, prefix=f"{prefix}{key}.")
        else:
            if raw is None:
                continue
            setattr(obj, key, _coerce(raw, current))
    return obj


def _update_from_dict(obj: T, data: dict[str, Any] | None) -> T:
    if data:
        _apply_dict(obj, data)
    return obj


@dataclass
class IndicatorConfig:
    # plan 2.1 - 2.6 / 5
    atr_len: int = 14
    st_mult: float = 2.0
    ema_len: int = 100
    jma_len: int = 7
    jma_phase: int = 50
    jma_power: int = 2
    rsi_len: int = 14
    rsi_mode: str = "wilder"  # wilder | sma (sma matches Kiwoom formula parser)
    vwap_sigma_floor_pct: float = 0.003


@dataclass
class BaselineConfig:
    # plan 3.1 / 5
    base_days: int = 20
    base_smooth: int = 2
    base_floor: float = 0.5
    base_min_days: int = 10
    min_bars_per_day: int = 60  # exclude suspended / half-day curves
    ipo_exclude_days: int = 5  # listing-day based exclusion


@dataclass
class DelayConfig:
    # plan 4.2
    d_max: float = 1.5
    vi_static_pct: float = 0.10
    vi_buffer_pct: float = 0.02
    limit_zone_pct: float = 0.25
    vi_cooldown_min: int = 3
    gap_pct: float = 0.05
    bar_ret_pct: float = 0.02
    bar_lookback: int = 2
    max_day_ret: float = 0.20
    # A fresh up-flip measures extension from the broken band before using the ST line.
    ext_ref: str = "breakout"
    ext_max: float = 1.0
    ext_fresh_bars: int = 10
    # VI release feed is not part of the REST chart API.  0 = filter disabled.
    vi_release_hhmm: str | None = None


@dataclass
class RearmConfig:
    # plan 4.3
    mode: str = "EITHER"  # ST | JMA | EITHER
    jma_min_down: int = 3
    pb_atr: float = 0.7
    defer_max_bars: int = 90
    inv_atr: float = 0.5
    st_require_above_ema: bool = True


@dataclass
class ConfirmConfig:
    # plan 4.4
    window: int = 3
    fail_action: str = "DEFER"  # IDLE | DEFER
    use_value: bool = True
    min_bar_value: float = 50_000_000.0
    use_vwap: bool = True
    use_rti: bool = True
    min_rti: float = 2.0
    min_rti_tick: float = 2.0
    use_buy_ratio: bool = True
    min_buy_ratio: float = 0.55
    use_rsi: bool = False
    rsi_lo: float = 50.0
    rsi_hi: float = 80.0
    use_score: bool = False
    min_score: float = 50.0


@dataclass
class ExitConfig:
    # plan 4.6 / 4.7
    stop_enabled: bool = True
    stop_buf_ticks: int = 1
    trail_enabled: bool = True
    tp_enabled: bool = False
    tp_r: float = 2.0
    tp_frac: float = 0.5
    tp_move_stop_to_entry: bool = False
    exh_enabled: bool = False
    exh_rti: float = 4.0
    exh_er: float = 0.1
    exh_k: int = 5
    eod_exit: str = "15:15"
    last_entry_time: str = "15:10"
    max_hold_bars: int | None = None
    max_entries_per_day: int = 2
    reentry_cooldown: int = 5
    allow_overnight: bool = False


@dataclass
class RiskConfig:
    initial_capital: float = 100_000_000.0
    risk_per_trade: float = 0.005
    max_positions: int = 3
    max_position_weight: float = 0.34
    commission: float = 0.00015  # 편도
    tax: float = 0.0020  # 매도
    slip_ticks: int = 1
    # plan 8.1 stage 1 -> stage 2 switch.  When False the score is still
    # computed and logged, but it does not gate or size entries.
    enforce_grade: bool = False
    grade_multipliers: dict[str, float] = field(
        default_factory=lambda: {"A": 1.0, "B": 0.6, "C": 0.0}
    )


@dataclass
class ScoreConfig:
    # plan 7.2 - 7.5
    enabled: bool = True
    mode: str = "linear"  # linear | geo
    min_component: float = 0.3
    u_weights: tuple[float, float, float] = (0.50, 0.25, 0.25)
    u1_tri: tuple[float, float, float, float] = (0.0, 0.5, 2.0, 3.5)
    u2_lin: tuple[float, float] = (0.0, 0.5)
    u3_lin: tuple[float, float] = (0.5, 0.9)
    m_weights: tuple[float, float, float, float, float, float] = (
        0.30,
        0.15,
        0.20,
        0.20,
        0.10,
        0.05,
    )
    m1_lin: tuple[float, float] = (0.0, 2.58)  # log2 RTI
    m2_lin: tuple[float, float] = (1.0, 2.5)
    m3_lin: tuple[float, float] = (0.5, 0.7)
    m4_lin: tuple[float, float] = (0.0, 0.4)
    m5_lin: tuple[float, float] = (1.0, 2.0)
    m6_percentiles: tuple[float, float] = (50.0, 95.0)
    p_ext_lin: tuple[float, float] = (1.0, 2.5)
    p_ext_lin_breakout: tuple[float, float] = (0.5, 1.5)
    m1_lin_tick: tuple[float, float] = (0.0, 2.58)
    m4_lin_tick: tuple[float, float] = (0.0, 0.4)
    p_div_er_tick: float = 0.1
    p_vi_lin: tuple[float, float] = (0.0, 0.03)
    p_div_rti: float = 4.0
    p_div_er: float = 0.1
    p_div_penalty: float = 0.3
    grade_a: float = 70.0
    grade_b: float = 50.0
    score_drop_warn: float = 30.0


@dataclass
class DataConfig:
    symbols: list[str] = field(default_factory=lambda: ["005930"])
    start: str | None = None  # YYYY-MM-DD
    end: str | None = None
    days: int = 30  # backtest trading days when start is not given
    include_nxt: bool = False
    session_start: str = "09:01"
    session_end: str = "15:20"
    bar_interval: int = 1
    feature_mode: str = "auto"  # auto | bar | tick
    assumed_trade_size: float = 1.0  # bar mode: volume -> trade-count proxy
    cache_dir: str = ".cache"
    # Extra calendar days fetched before the backtest start for EMA/base warmup.
    warmup_days: int = 45
    allow_unresolved: bool = False


@dataclass
class BacktestConfig:
    data: DataConfig = field(default_factory=DataConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    delay: DelayConfig = field(default_factory=DelayConfig)
    rearm: RearmConfig = field(default_factory=RearmConfig)
    confirm: ConfirmConfig = field(default_factory=ConfirmConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)

    # portfolio selection / housekeeping
    selection: str = "time"  # score | time | random  (stage 1 = time)
    random_seed: int = 7
    use_mock: bool | None = None  # None = follow .env
    out_dir: str = "runs/latest"
    plot: bool = False
    verbose: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BacktestConfig":
        cfg = cls()
        _update_from_dict(cfg, data)
        return cfg

    @classmethod
    def from_json(cls, path: str | Path) -> "BacktestConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.data.feature_mode not in ("auto", "bar", "tick"):
            raise ValueError("data.feature_mode must be auto, bar or tick")
        if self.rearm.mode.upper() not in ("ST", "JMA", "EITHER"):
            raise ValueError("rearm.mode must be ST, JMA or EITHER")
        if self.confirm.fail_action.upper() not in ("IDLE", "DEFER"):
            raise ValueError("confirm.fail_action must be IDLE or DEFER")
        if self.selection not in ("score", "time", "random"):
            raise ValueError("selection must be score, time or random")
        if self.data.bar_interval < 1:
            raise ValueError("data.bar_interval must be >= 1")
        if self.risk.max_positions < 1:
            raise ValueError("risk.max_positions must be >= 1")
        if not 0 < self.risk.risk_per_trade <= 1:
            raise ValueError("risk.risk_per_trade must be in (0, 1]")
        if not 0 < self.risk.max_position_weight <= 1:
            raise ValueError("risk.max_position_weight must be in (0, 1]")
        if self.score.mode not in ("linear", "geo"):
            raise ValueError("score.mode must be linear or geo")
        if self.score.enabled:
            if abs(sum(self.score.u_weights) - 1.0) > 1e-9:
                raise ValueError("score.u_weights must sum to 1")
            if abs(sum(self.score.m_weights) - 1.0) > 1e-9:
                raise ValueError("score.m_weights must sum to 1")
        if self.delay.ext_ref not in ("breakout", "st_line"):
            raise ValueError("delay.ext_ref must be breakout or st_line")
        if self.delay.ext_fresh_bars < 0:
            raise ValueError("delay.ext_fresh_bars must be >= 0")
