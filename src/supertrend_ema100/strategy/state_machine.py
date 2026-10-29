"""Per-symbol state machine (plan 4.5)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from ..config import BacktestConfig
from ..data.series import SymbolSeries
from ..data.universe import capture_minute, parse_hhmmss, watch_phase
from ..indicators.basic import round_to_tick, tick_size
from ..indicators.extension import extension_value
from .filters import (
    confirm_checks,
    day_blocked,
    delay_reasons,
    is_trigger,
    rearm_event,
    trig_state,
)


class State(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    IN_POS = "IN_POS"


@dataclass(slots=True)
class StrategyEvent:
    ts: str
    code: str
    name: str
    kind: str
    state_from: str
    state_to: str
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    score: float = 0.0
    grade: str = "C"
    note: str = ""
    # feature snapshot
    close: float = 0.0
    d_value: float | None = None
    ext_value: float | None = None
    ext_kind: str = ""
    rti_1: float | None = None
    rti_3: float | None = None
    rti_10: float | None = None
    accel: float | None = None
    buy_ratio: float | None = None
    er_tick: float | None = None
    atv_ratio: float | None = None
    tov: float | None = None
    vwap: float | None = None
    ema: float | None = None
    st: float | None = None
    atr: float | None = None
    day_ret: float | None = None
    baseline_ready: bool = False
    feature_mode: str = "bar"


@dataclass(slots=True)
class EntryIntent:
    code: str
    name: str
    signal_index: int
    signal_ts: str
    signal_close: float
    stop: float
    score: float
    grade: str
    multiplier: float
    reasons: list[str]
    checks: dict[str, bool]
    tov: float | None = None
    filter_snapshot: dict[str, str] = field(default_factory=dict)


def _snapshot(series: SymbolSeries, i: int, cfg: BacktestConfig) -> dict[str, object]:
    bar = series.bars[i]
    atr = series.atr[i]
    d_value = (bar.close - series.st[i]) / atr if atr > 0 else None
    ext, _limit, ext_kind = extension_value(
        i,
        bar.close,
        atr,
        series.st[i],
        series.direction,
        series.st_upper,
        ref=cfg.delay.ext_ref,
        d_max=cfg.delay.d_max,
        ext_max=cfg.delay.ext_max,
        fresh_bars=cfg.delay.ext_fresh_bars,
    )
    return {
        "close": bar.close,
        "d_value": d_value,
        "ext_value": ext,
        "ext_kind": ext_kind,
        "rti_1": series.features.rti_1[i],
        "rti_3": series.features.rti_3[i],
        "rti_10": series.features.rti_10[i],
        "accel": series.features.accel[i],
        "buy_ratio": series.features.buy_ratio_5[i],
        "er_tick": series.features.er_5[i],
        "atv_ratio": series.features.atv_ratio_5[i],
        "tov": series.features.tov_5[i],
        "vwap": series.vwap[i],
        "ema": series.ema[i],
        "st": series.st[i],
        "atr": atr,
        "day_ret": series.day_ret[i],
        "baseline_ready": series.features.baseline_ready[i],
        "feature_mode": series.feature_mode,
    }


def _event(
    series: SymbolSeries,
    i: int,
    cfg: BacktestConfig,
    kind: str,
    state_from: State,
    state_to: State,
    *,
    reasons: list[str] | None = None,
    checks: dict[str, bool] | None = None,
    note: str = "",
    score: float | None = None,
    grade: str | None = None,
) -> StrategyEvent:
    snapshot = _snapshot(series, i, cfg)
    bar_score = series.scores[i]
    return StrategyEvent(
        ts=series.bars[i].ts,
        code=series.code,
        name=series.name,
        kind=kind,
        state_from=state_from.value,
        state_to=state_to.value,
        reasons=list(reasons or []),
        checks=dict(checks or {}),
        score=bar_score.score if score is None else score,
        grade=bar_score.grade if grade is None else grade,
        note=note,
        **snapshot,  # type: ignore[arg-type]
    )


class SymbolStateMachine:
    def __init__(self, series: SymbolSeries) -> None:
        self.series = series
        self.state = State.IDLE
        self.t0 = 0
        self.current_day = ""
        self.entries_today = 0
        self.last_exit_index: int | None = None
        self.gap_consumed = False
        self.last_intent: EntryIntent | None = None
        self.events: list[StrategyEvent] = []
        self.prewatch_armed = False

    def _reset_day(self, day: str) -> None:
        if day != self.current_day:
            self.current_day = day
            self.entries_today = 0
            self.gap_consumed = False
            self.prewatch_armed = False

    def on_exit(self, index: int) -> None:
        self.state = State.IDLE
        self.last_exit_index = index
        self.last_intent = None

    def on_entry_filled(self) -> None:
        self.state = State.IN_POS
        self.entries_today += 1

    def on_entry_rejected(self, index: int, note: str = "rejected") -> list[StrategyEvent]:
        events = []
        if self.state == State.IN_POS:
            intent = self.last_intent
            events.append(
                _event(
                    self.series,
                    index,
                    self._cfg,
                    "REJECT",
                    State.IN_POS,
                    State.IDLE,
                    note=note,
                    score=intent.score if intent is not None else None,
                    grade=intent.grade if intent is not None else None,
                )
            )
        self.state = State.IDLE
        return events

    # The state machine needs the config for snapshots; it is always called
    # from the engine with the same object.
    _cfg: BacktestConfig

    def on_bar(
        self,
        i: int,
        cfg: BacktestConfig,
        *,
        vi_release_minute: int | None = None,
    ) -> tuple[list[StrategyEvent], EntryIntent | None]:
        self._cfg = cfg
        series = self.series
        bar = series.bars[i]
        self._reset_day(bar.day)
        events: list[StrategyEvent] = []
        intent: EntryIntent | None = None
        state_before = self.state

        if self.state == State.IN_POS:
            return events, None

        phase = watch_phase(
            series.capture,
            bar.day,
            bar.minute_of_day,
            capture_minute(parse_hhmmss(cfg.universe.watch_start)),
        )
        if phase == "off":
            self.state = State.IDLE
            self.prewatch_armed = False
            return events, None
        if phase == "pre":
            if self.state == State.PENDING:
                self.state, self.t0 = State.DEFERRED, i
            elif (
                self.state == State.IDLE
                and cfg.universe.prewatch_trigger != "ignore"
                and is_trigger(series, i)
            ):
                self.state, self.t0 = State.DEFERRED, i
                self.prewatch_armed = True
                events.append(
                    _event(
                        series,
                        i,
                        cfg,
                        "T1",
                        State.IDLE,
                        State.DEFERRED,
                        reasons=["PREWATCH"],
                    )
                )
            return events, None

        if day_blocked(series, i, cfg):
            if self.state != State.IDLE:
                events.append(
                    _event(
                        series,
                        i,
                        cfg,
                        "BLOCK",
                        self.state,
                        State.IDLE,
                        note="max_day_ret",
                    )
                )
            self.state = State.IDLE
            return events, None

        trig = is_trigger(series, i)
        if self.prewatch_armed and self.state == State.DEFERRED:
            self.prewatch_armed = False
            if cfg.universe.prewatch_trigger == "carry" and trig_state(series, i):
                trig = True

        if self.state == State.IDLE:
            if trig:
                # Re-entry rules.
                if (
                    self.entries_today >= cfg.exits.max_entries_per_day
                    or (
                        self.last_exit_index is not None
                        and i - self.last_exit_index < cfg.exits.reentry_cooldown
                    )
                ):
                    events.append(
                        _event(
                            series,
                            i,
                            cfg,
                            "T1",
                            State.IDLE,
                            State.IDLE,
                            note="cooldown_or_max_entries",
                        )
                    )
                    return events, None
                reasons = delay_reasons(
                    series,
                    i,
                    cfg,
                    check_gap=True,
                    gap_consumed=self.gap_consumed,
                    vi_release_minute=vi_release_minute,
                )
                if reasons:
                    self.state = State.DEFERRED
                    self.t0 = i
                    if "GAP" in reasons:
                        self.gap_consumed = True
                    events.append(
                        _event(
                            series,
                            i,
                            cfg,
                            "T1",
                            State.IDLE,
                            State.DEFERRED,
                            reasons=reasons,
                        )
                    )
                else:
                    self.state = State.PENDING
                    self.t0 = i
                    events.append(
                        _event(
                            series,
                            i,
                            cfg,
                            "T1",
                            State.IDLE,
                            State.PENDING,
                        )
                    )
            return events, None

        if self.state == State.DEFERRED:
            invalid = (
                bar.close < series.ema[i] - cfg.rearm.inv_atr * series.atr[i]
                or i - self.t0 > cfg.rearm.defer_max_bars
            )
            if invalid:
                events.append(
                    _event(
                        series,
                        i,
                        cfg,
                        "INVALIDATE",
                        State.DEFERRED,
                        State.IDLE,
                        note="ema_break" if bar.close < series.ema[i] - cfg.rearm.inv_atr * series.atr[i] else "defer_max_bars",
                    )
                )
                self.state = State.IDLE
                return events, None
            if rearm_event(series, i, cfg) or trig:
                reasons = delay_reasons(
                    series,
                    i,
                    cfg,
                    check_gap=False,
                    gap_consumed=self.gap_consumed,
                    vi_release_minute=vi_release_minute,
                )
                if not reasons:
                    self.state = State.PENDING
                    self.t0 = i
                    events.append(
                        _event(
                            series,
                            i,
                            cfg,
                            "REARM",
                            State.DEFERRED,
                            State.PENDING,
                        )
                    )
                else:
                    events.append(
                        _event(
                            series,
                            i,
                            cfg,
                            "REARM",
                            State.DEFERRED,
                            State.DEFERRED,
                            reasons=reasons,
                        )
                    )
            return events, None

        # PENDING
        reasons = delay_reasons(
            series,
            i,
            cfg,
            check_gap=False,
            gap_consumed=self.gap_consumed,
            vi_release_minute=vi_release_minute,
        )
        if reasons:
            self.state = State.DEFERRED
            self.t0 = i
            events.append(
                _event(
                    series,
                    i,
                    cfg,
                    "REDELAY",
                    State.PENDING,
                    State.DEFERRED,
                    reasons=reasons,
                )
            )
            return events, None

        checks = confirm_checks(series, i, cfg)
        if checks.passed:
            stop_buf = cfg.exits.stop_buf_ticks * tick_size(series.st[i])
            stop = round_to_tick(series.st[i]) - stop_buf
            score = series.scores[i]
            intent = EntryIntent(
                code=series.code,
                name=series.name,
                signal_index=i,
                signal_ts=bar.ts,
                signal_close=bar.close,
                stop=stop,
                score=score.score,
                grade=score.grade,
                multiplier=score.multiplier if cfg.risk.enforce_grade else 1.0,
                reasons=[],
                checks=checks.checks,
                tov=series.features.tov_5[i],
                filter_snapshot={
                    "feature_mode": series.feature_mode,
                    "upward_score": f"{score.u:.4f}",
                    "market_score": f"{score.m:.4f}",
                    "penalty": f"{score.p:.4f}",
                },
            )
            self.state = State.IN_POS
            self.t0 = i
            self.last_intent = intent
            events.append(
                _event(
                    series,
                    i,
                    cfg,
                    "ENTRY",
                    State.PENDING,
                    State.IN_POS,
                    checks=checks.checks,
                )
            )
            return events, intent

        if i - self.t0 >= cfg.confirm.window:
            next_state = (
                State.IDLE if cfg.confirm.fail_action.upper() == "IDLE" else State.DEFERRED
            )
            self.state = next_state
            self.t0 = i
            events.append(
                _event(
                    series,
                    i,
                    cfg,
                    "CONFIRM_FAIL",
                    State.PENDING,
                    next_state,
                    checks=checks.checks,
                    reasons=checks.failed(),
                )
            )
        return events, None
