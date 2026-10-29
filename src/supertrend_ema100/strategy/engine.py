"""Event-driven backtest engine (plan 6).

Timing contract: a decision is made on bar t's close and filled on t+1's open.
No same-bar close is ever used as a fill.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Iterable

from ..config import BacktestConfig
from ..data.loader import LoadedData, hhmm_to_minutes
from ..data.series import SymbolSeries
from ..indicators.basic import round_to_tick, tick_size
from .portfolio import Portfolio, Position, Trade, ts_to_datetime
from .state_machine import (
    EntryIntent,
    State,
    StrategyEvent,
    SymbolStateMachine,
    _event,
)


@dataclass(slots=True)
class PendingEntry:
    intent: EntryIntent
    due_ts: str
    next_index: int
    order_key: tuple


@dataclass(slots=True)
class VirtualTrade:
    vid: str
    code: str
    name: str
    signal_ts: str
    reasons: str
    entry_ts: str = ""
    entry_price: float = 0.0
    initial_stop: float = 0.0
    stop: float = 0.0
    entry_index: int = -1
    exit_index: int = -1
    active: bool = False
    exited: bool = False
    exit_ts: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    mae_r: float = 0.0
    mfe_r: float = 0.0
    highest: float = 0.0
    lowest: float = 0.0
    feature_mode: str = "bar"
    pending_exit_reason: str | None = None
    pending_exit_due: str | None = None

    def to_trade(self, cfg: BacktestConfig) -> Trade:
        risk = max(self.entry_price - self.initial_stop, 1e-9)
        entry_fee = self.entry_price * cfg.risk.commission
        sell_fee = self.exit_price * cfg.risk.commission
        tax = self.exit_price * cfg.risk.tax
        net = (self.exit_price - self.entry_price) - (entry_fee + sell_fee + tax)
        try:
            hold_minutes = (
                ts_to_datetime(self.exit_ts) - ts_to_datetime(self.entry_ts)
            ).total_seconds() / 60.0
        except (TypeError, ValueError):
            hold_minutes = 0.0
        return Trade(
            code=self.code,
            name=self.name,
            grade="-",
            score=0.0,
            entry_ts=self.entry_ts,
            exit_ts=self.exit_ts,
            entry_price=self.entry_price,
            exit_price=self.exit_price,
            qty=1.0,
            initial_stop=self.initial_stop,
            risk_per_share=risk,
            risk_amount=risk,
            net_pnl=net,
            pnl_pct=net / self.entry_price if self.entry_price else 0.0,
            r_multiple=net / risk,
            gross_r=(self.exit_price - self.entry_price) / risk,
            mae_r=self.mae_r,
            mfe_r=self.mfe_r,
            hold_bars=max(1, self.exit_index - self.entry_index)
            if self.exit_index >= self.entry_index >= 0
            else 1,
            hold_minutes=hold_minutes,
            exit_reason=self.exit_reason,
            entry_fee=entry_fee,
            sell_fee=sell_fee,
            tax=tax,
            partial_qty=1.0,
            partial_pnl=net,
            feature_mode=self.feature_mode,
            signal_ts=self.signal_ts,
            deferred_id=self.vid,
            deferred_reasons=self.reasons,
            counterfactual=True,
        )


def _random_key(seed: int, code: str, ts: str) -> int:
    text = f"{seed}:{code}:{ts}".encode("utf-8")
    return int(hashlib.sha1(text).hexdigest()[:12], 16)


class BacktestEngine:
    def __init__(self, cfg: BacktestConfig, data: LoadedData) -> None:
        self.cfg = cfg
        self.data = data
        self.series = data.series
        self.portfolio = Portfolio.create(cfg)
        self.sms: dict[str, SymbolStateMachine] = {
            code: SymbolStateMachine(s) for code, s in self.series.items()
        }
        self.events: list[StrategyEvent] = []
        self.virtual_trades: list[VirtualTrade] = []
        self.pending: list[PendingEntry] = []
        self.last_deferred: dict[str, VirtualTrade] = {}
        self._virtual_counter = 0
        self.warnings = list(data.warnings)
        self._last_prices: dict[str, float] = {}
        self._day_last: dict[str, dict[str, int]] = {}
        self._event_indices: dict[str, list[int]] = {}
        self._by_ts: dict[str, list[tuple[str, int]]] = {}
        self._timeline: list[str] = []
        self._prepare()

    def _prepare(self) -> None:
        start, end = self.data.start_date, self.data.end_date
        by_ts: dict[str, list[tuple[str, int]]] = {}
        timeline: set[str] = set()
        for code, series in self.series.items():
            indices = [
                i
                for i, bar in enumerate(series.bars)
                if start <= bar.day <= end
            ]
            self._event_indices[code] = indices
            if indices and not series.ready[indices[0]]:
                self.warnings.append(
                    f"{series.name}({code}): 백테스트 시작 시점 ATR 워밍업 미완료"
                )
            day_last: dict[str, int] = {}
            for i in indices:
                bar = series.bars[i]
                by_ts.setdefault(bar.ts, []).append((code, i))
                timeline.add(bar.ts)
                day_last[bar.day] = max(day_last.get(bar.day, i), i)
            self._day_last[code] = day_last
            if series.bars:
                self._last_prices[code] = series.bars[indices[0]].open if indices else series.bars[-1].close
        self._by_ts = by_ts
        self._timeline = sorted(timeline)

    # ------------------------------------------------------------------ util
    def _next_index(self, series: SymbolSeries, i: int) -> int | None:
        return i + 1 if i + 1 < len(series.bars) else None

    def _entry_allowed(self, series: SymbolSeries, i: int) -> tuple[bool, str]:
        nxt = self._next_index(series, i)
        if nxt is None:
            return False, "no_next_bar"
        current = series.bars[i]
        nxt_bar = series.bars[nxt]
        if not self.cfg.exits.allow_overnight and nxt_bar.day != current.day:
            return False, "overnight"
        last_entry = hhmm_to_minutes(self.cfg.exits.last_entry_time)
        if nxt_bar.minute_of_day > last_entry:
            return False, "late_entry"
        if nxt_bar.minute_of_day >= hhmm_to_minutes(self.cfg.exits.eod_exit):
            return False, "after_eod"
        return True, ""

    def _order_key(self, intent: EntryIntent) -> tuple:
        mode = self.cfg.selection
        if mode == "score":
            return (-intent.score, -(intent.tov or 0.0), intent.code)
        if mode == "time":
            return (intent.signal_ts, intent.code)
        return (_random_key(self.cfg.random_seed, intent.code, intent.signal_ts),)

    def _rank_pending(self, pending: list[PendingEntry]) -> list[PendingEntry]:
        return sorted(pending, key=lambda p: p.order_key)

    # --------------------------------------------------------------- entries
    def _flush_pending(self, ts: str) -> None:
        due = [p for p in self.pending if p.due_ts == ts]
        if not due:
            return
        self.pending = [p for p in self.pending if p.due_ts != ts]
        equity = self.portfolio.equity(self._last_prices)
        for item in self._rank_pending(due):
            intent = item.intent
            series = self.series[intent.code]
            sm = self.sms[intent.code]
            if not self.portfolio.can_open(intent.code):
                self.events.extend(sm.on_entry_rejected(item.next_index, "no_slot"))
                continue
            bar = series.bars[item.next_index]
            slip = self.cfg.risk.slip_ticks * tick_size(bar.open)
            entry_price = bar.open + slip
            if entry_price <= intent.stop:
                self.events.extend(sm.on_entry_rejected(item.next_index, "stop_above_entry"))
                continue
            pos = self.portfolio.open(
                intent, entry_price, bar.ts, item.next_index, equity_now=equity
            )
            if pos is None:
                self.events.extend(sm.on_entry_rejected(item.next_index, "size_zero"))
                continue
            sm.on_entry_filled()
            self.events.append(
                _event(
                    series,
                    item.next_index,
                    self.cfg,
                    "FILL",
                    State.PENDING,
                    State.IN_POS,
                    note=f"price={entry_price:.4f};qty={int(pos.qty)}",
                    score=intent.score,
                    grade=intent.grade,
                )
            )
            self.last_deferred.pop(intent.code, None)
            equity = self.portfolio.equity(self._last_prices)

    # ----------------------------------------------------------------- exits
    def _close_position(
        self, pos: Position, price: float, ts: str, index: int, reason: str
    ) -> None:
        trade = self.portfolio.sell(pos, pos.qty, price, ts, index, reason)
        if trade is not None:
            series = self.series[pos.code]
            self.sms[pos.code].on_exit(index)
            self.events.append(
                _event(
                    series,
                    index,
                    self.cfg,
                    "EXIT",
                    State.IN_POS,
                    State.IDLE,
                    note=f"{reason};r={trade.r_multiple:.2f}",
                    score=pos.score,
                    grade=pos.grade,
                )
            )

    def _schedule_exit(self, pos: Position, reason: str, due_ts: str | None) -> None:
        if due_ts:
            pos.pending_exit_reason = reason
            pos.pending_exit_due = due_ts

    def _process_position(
        self, code: str, i: int, series: SymbolSeries
    ) -> None:
        pos = self.portfolio.positions.get(code)
        if pos is None:
            return
        bar = series.bars[i]
        pos.update_excursion(bar.high, bar.low)

        # A scheduled exit (ST flip / exhaustion / max hold) fills at this open.
        if pos.pending_exit_due == bar.ts and pos.pending_exit_reason:
            raw = bar.open
            fill = raw - self.cfg.risk.slip_ticks * tick_size(raw)
            reason = pos.pending_exit_reason
            pos.pending_exit_reason = None
            pos.pending_exit_due = None
            self._close_position(pos, fill, bar.ts, i, reason)
            return

        # X_STOP has priority over take-profit in the same bar.
        if self.cfg.exits.stop_enabled and bar.low <= pos.stop:
            raw = bar.open if bar.open < pos.stop else pos.stop
            fill = raw - self.cfg.risk.slip_ticks * tick_size(raw)
            self._close_position(pos, fill, bar.ts, i, "X_STOP")
            return

        # Partial take-profit.
        if self.cfg.exits.tp_enabled and not pos.tp_done:
            target = pos.entry_price + self.cfg.exits.tp_r * pos.risk_per_share
            if bar.high >= target:
                fill = target - self.cfg.risk.slip_ticks * tick_size(target)
                frac = max(0.0, min(1.0, self.cfg.exits.tp_frac))
                qty = math.floor(pos.original_qty * frac)
                if frac >= 1.0:
                    qty = int(pos.qty)
                if 0 < qty < pos.qty:
                    self.portfolio.sell(pos, qty, fill, bar.ts, i, "X_TP")
                elif qty >= pos.qty:
                    self._close_position(pos, fill, bar.ts, i, "X_TP")
                if pos.code in self.portfolio.positions:
                    pos.tp_done = True

        # Exhaustion: high RTI + poor path efficiency + no new high.
        if self.cfg.exits.exh_enabled and pos.code in self.portfolio.positions:
            rti = series.features.rti_3[i]
            er = series.features.er_5[i]
            exh_k = max(1, self.cfg.exits.exh_k)
            no_new_high = False
            if i >= exh_k:
                prev_high = max(series.bars[j].high for j in range(i - exh_k, i))
                no_new_high = bar.high <= prev_high
            if (
                rti is not None
                and er is not None
                and rti >= self.cfg.exits.exh_rti
                and er < self.cfg.exits.exh_er
                and no_new_high
            ):
                nxt = self._next_index(series, i)
                self._schedule_exit(
                    pos, "X_EXH", series.bars[nxt].ts if nxt is not None else None
                )

        # ST flip at the close -> next bar's open.
        if self.cfg.exits.trail_enabled and series.direction[i] == -1:
            nxt = self._next_index(series, i)
            self._schedule_exit(
                pos, "X_TRAIL_FLIP", series.bars[nxt].ts if nxt is not None else None
            )

        # Max holding time.
        if self.cfg.exits.max_hold_bars and (i - pos.entry_index) >= self.cfg.exits.max_hold_bars:
            nxt = self._next_index(series, i)
            self._schedule_exit(
                pos, "X_TIME_MAX", series.bars[nxt].ts if nxt is not None else None
            )

        # Trail the stop with the Supertrend line (tick-aligned).
        if self.cfg.exits.trail_enabled and series.direction[i] == 1:
            pos.stop = max(pos.stop, round_to_tick(series.st[i]))

        # Plan 7.6: flag a held position whose score collapsed while
        # divergence is present.  This is a monitoring alert, not an exit.
        if self.cfg.score.enabled and not pos.score_alerted:
            current = series.scores[i]
            if (
                pos.score - current.score >= self.cfg.score.score_drop_warn
                and current.p_div > 0
            ):
                pos.score_alerted = True
                self.events.append(
                    _event(
                        series,
                        i,
                        self.cfg,
                        "SCORE_DROP",
                        State.IN_POS,
                        State.IN_POS,
                        note=f"entry={pos.score:.1f};now={current.score:.1f};p_div={current.p_div:.2f}",
                    )
                )

        # End-of-day: decide on this close, fill on the next bar's open.
        if bar.minute_of_day >= hhmm_to_minutes(self.cfg.exits.eod_exit):
            nxt = self._next_index(series, i)
            if nxt is not None and series.bars[nxt].day == bar.day:
                self._schedule_exit(pos, "X_EOD", series.bars[nxt].ts)
                return
            self._close_position(pos, bar.close, bar.ts, i, "X_EOD")
            return

        # Safety: never hold overnight unless explicitly allowed.
        if not self.cfg.exits.allow_overnight:
            last = self._day_last.get(code, {}).get(bar.day)
            if last == i:
                self._close_position(pos, bar.close, bar.ts, i, "X_EOD")

    # -------------------------------------------------------------- virtuals
    def _update_virtuals(self, code: str, i: int, series: SymbolSeries) -> None:
        bar = series.bars[i]
        for vt in list(self._active_virtuals_for(code)):
            if not vt.active and not vt.exited and vt.entry_index == i:
                slip = self.cfg.risk.slip_ticks * tick_size(bar.open)
                vt.entry_price = bar.open + slip
                vt.entry_ts = bar.ts
                vt.entry_index = i
                if vt.initial_stop > 0 and vt.entry_price > vt.initial_stop:
                    vt.active = True
                    vt.stop = vt.initial_stop
                    vt.highest = vt.entry_price
                    vt.lowest = vt.entry_price
                else:
                    vt.exited = True
                    vt.exit_reason = "invalid_stop"
                    vt.exit_ts = bar.ts
                    vt.exit_price = vt.entry_price
                    vt.exit_index = i
                    self.virtual_trades.append(vt)
                    continue
                # A position opened on the session's last bar cannot be held.
                if bar.minute_of_day >= hhmm_to_minutes(self.cfg.exits.eod_exit):
                    vt.exit_price = bar.close
                    vt.exit_ts = bar.ts
                    vt.exit_index = i
                    vt.exit_reason = "X_EOD"
                    vt.exited = True
                    self.virtual_trades.append(vt)
                continue
            if not vt.active or vt.exited:
                continue
            if vt.pending_exit_due == bar.ts and vt.pending_exit_reason:
                vt.exit_price = bar.open - self.cfg.risk.slip_ticks * tick_size(bar.open)
                vt.exit_ts = bar.ts
                vt.exit_index = i
                vt.exit_reason = vt.pending_exit_reason
                vt.exited = True
                self.virtual_trades.append(vt)
                continue
            risk = max(vt.entry_price - vt.initial_stop, 1e-9)
            vt.highest = max(vt.highest, bar.high)
            vt.lowest = min(vt.lowest, bar.low)
            vt.mfe_r = max(vt.mfe_r, (bar.high - vt.entry_price) / risk)
            vt.mae_r = min(vt.mae_r, (bar.low - vt.entry_price) / risk)
            if self.cfg.exits.stop_enabled and bar.low <= vt.stop:
                raw = bar.open if bar.open < vt.stop else vt.stop
                vt.exit_price = raw - self.cfg.risk.slip_ticks * tick_size(raw)
                vt.exit_ts = bar.ts
                vt.exit_index = i
                vt.exit_reason = "X_STOP"
                vt.exited = True
                self.virtual_trades.append(vt)
                continue
            if self.cfg.exits.trail_enabled and series.direction[i] == -1:
                vt.pending_exit_reason = "X_TRAIL_FLIP"
                nxt = self._next_index(series, i)
                vt.pending_exit_due = series.bars[nxt].ts if nxt is not None else None
            if self.cfg.exits.trail_enabled and series.direction[i] == 1:
                vt.stop = max(vt.stop, round_to_tick(series.st[i]))
            if bar.minute_of_day >= hhmm_to_minutes(self.cfg.exits.eod_exit):
                nxt = self._next_index(series, i)
                if nxt is not None and series.bars[nxt].day == bar.day:
                    vt.pending_exit_reason = "X_EOD"
                    vt.pending_exit_due = series.bars[nxt].ts
                    continue
                vt.exit_price = bar.close
                vt.exit_ts = bar.ts
                vt.exit_index = i
                vt.exit_reason = "X_EOD"
                vt.exited = True
                self.virtual_trades.append(vt)

    def _active_virtuals_for(self, code: str) -> Iterable[VirtualTrade]:
        # Virtual trades are stored on the instance until they exit.
        for vt in getattr(self, "_virtuals", []):
            if vt.code == code and not vt.exited:
                yield vt

    # ------------------------------------------------------------------- run
    def run(self) -> "BacktestResult":
        self._virtuals: list[VirtualTrade] = []
        eod_minute = hhmm_to_minutes(self.cfg.exits.eod_exit)

        for ts in self._timeline:
            # 1) Entries scheduled for this bar's open.
            self._flush_pending(ts)

            # 2) Process every symbol bar at this timestamp.
            for code, i in self._by_ts.get(ts, []):
                series = self.series[code]
                bar = series.bars[i]

                self._process_position(code, i, series)
                self._update_virtuals(code, i, series)

                if code not in self.portfolio.positions and self.sms[code].state != State.IN_POS:
                    events, intent = self.sms[code].on_bar(
                        i,
                        self.cfg,
                        vi_release_minute=(
                            hhmm_to_minutes(self.cfg.delay.vi_release_hhmm)
                            if self.cfg.delay.vi_release_hhmm
                            else None
                        ),
                    )
                    self.events.extend(events)
                    # Track the deferred signal + its counterfactual trade.
                    for event in events:
                        if event.kind == "T1" and event.state_to == State.DEFERRED.value:
                            next_i = self._next_index(series, i)
                            allowed, _note = self._entry_allowed(series, i)
                            if not allowed or next_i is None:
                                # No immediate t+1 fill exists inside the entry
                                # window, so there is no honest counterfactual.
                                continue
                            self._virtual_counter += 1
                            vid = f"D{self._virtual_counter:05d}"
                            stop = round_to_tick(series.st[i]) - self.cfg.exits.stop_buf_ticks * tick_size(
                                series.st[i]
                            )
                            vt = VirtualTrade(
                                vid=vid,
                                code=code,
                                name=series.name,
                                signal_ts=bar.ts,
                                reasons="|".join(event.reasons),
                                initial_stop=stop,
                                stop=stop,
                                entry_index=next_i,
                                feature_mode=series.feature_mode,
                            )
                            self._virtuals.append(vt)
                            self.last_deferred[code] = vt
                        if event.kind in ("INVALIDATE",):
                            self.last_deferred.pop(code, None)

                    if intent is not None:
                        allowed, note = self._entry_allowed(series, i)
                        if not allowed:
                            self.events.extend(self.sms[code].on_entry_rejected(i, note))
                        else:
                            deferred = self.last_deferred.get(code)
                            if deferred is not None:
                                intent.filter_snapshot["deferred_id"] = deferred.vid
                                intent.filter_snapshot["deferred_reasons"] = deferred.reasons
                            nxt = self._next_index(series, i)
                            assert nxt is not None
                            self.pending.append(
                                PendingEntry(
                                    intent=intent,
                                    due_ts=series.bars[nxt].ts,
                                    next_index=nxt,
                                    order_key=self._order_key(intent),
                                )
                            )

                self._last_prices[code] = bar.close

            # 3) Mark the portfolio at this timestamp.
            equity = self.portfolio.equity(self._last_prices)
            self.portfolio.equity_points.append(
                (ts, equity, self.portfolio.cash, self.portfolio.exposure(self._last_prices))
            )

        # Close any leftover positions at the last known price.
        if self.portfolio.positions:
            last_ts = self._timeline[-1] if self._timeline else ""
            self.portfolio.force_close_all(self._last_prices, last_ts, "X_END")
        last_ts = self._timeline[-1] if self._timeline else ""
        for vt in self._virtuals:
            if vt.active and not vt.exited:
                vt.exit_price = self._last_prices.get(vt.code, vt.entry_price)
                vt.exit_ts = last_ts
                vt.exit_index = len(self.series[vt.code].bars) - 1
                vt.exit_reason = "X_END"
                vt.exited = True
                self.virtual_trades.append(vt)
        if self.portfolio.equity_points:
            ts, _, _, _ = self.portfolio.equity_points[-1]
            self.portfolio.equity_points.append(
                (
                    ts,
                    self.portfolio.equity(self._last_prices),
                    self.portfolio.cash,
                    self.portfolio.exposure(self._last_prices),
                )
            )

        return BacktestResult(
            cfg=self.cfg,
            data=self.data,
            events=self.events,
            trades=self.portfolio.trades,
            virtual_trades=[vt.to_trade(self.cfg) for vt in self.virtual_trades],
            equity_points=self.portfolio.equity_points,
            warnings=self.warnings,
        )


@dataclass
class BacktestResult:
    cfg: BacktestConfig
    data: LoadedData
    events: list[StrategyEvent]
    trades: list[Trade]
    virtual_trades: list[Trade]
    equity_points: list[tuple[str, float, float, float]]
    warnings: list[str] = field(default_factory=list)
