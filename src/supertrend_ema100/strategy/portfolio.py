"""Portfolio, position sizing and trade accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from ..config import BacktestConfig
from ..indicators.basic import tick_size
from .state_machine import EntryIntent


def ts_to_datetime(ts: str) -> datetime:
    text = ts.strip()
    for fmt, size in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12)):
        if len(text) >= size:
            try:
                return datetime.strptime(text[:size], fmt)
            except ValueError:
                continue
    return datetime.min


@dataclass(slots=True)
class Position:
    code: str
    name: str
    qty: float
    original_qty: float
    entry_price: float
    entry_ts: str
    entry_index: int
    stop: float
    initial_stop: float
    risk_per_share: float
    risk_amount: float
    grade: str
    score: float
    entry_fee: float
    signal_ts: str
    feature_mode: str
    deferred_id: str = ""
    deferred_reasons: str = ""
    partial_qty: float = 0.0
    partial_proceeds: float = 0.0
    partial_costs: float = 0.0
    partial_sell_fee: float = 0.0
    partial_tax: float = 0.0
    tp_done: bool = False
    score_alerted: bool = False
    mae_r: float = 0.0
    mfe_r: float = 0.0
    highest: float = 0.0
    lowest: float = 0.0
    pending_exit_reason: str | None = None
    pending_exit_due: str | None = None

    @property
    def remaining_qty(self) -> float:
        return max(0.0, self.qty)

    def update_excursion(self, high: float, low: float) -> None:
        if self.risk_per_share <= 0:
            return
        self.highest = max(self.highest, high)
        self.lowest = min(self.lowest, low) if self.lowest > 0 else low
        self.mfe_r = max(self.mfe_r, (high - self.entry_price) / self.risk_per_share)
        self.mae_r = min(self.mae_r, (low - self.entry_price) / self.risk_per_share)


@dataclass(slots=True)
class Trade:
    code: str
    name: str
    grade: str
    score: float
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    qty: float
    initial_stop: float
    risk_per_share: float
    risk_amount: float
    net_pnl: float
    pnl_pct: float
    r_multiple: float
    gross_r: float
    mae_r: float
    mfe_r: float
    hold_bars: int
    hold_minutes: float
    exit_reason: str
    entry_fee: float
    sell_fee: float
    tax: float
    partial_qty: float
    partial_pnl: float
    feature_mode: str
    signal_ts: str
    deferred_id: str = ""
    deferred_reasons: str = ""
    counterfactual: bool = False

    def to_row(self) -> dict[str, object]:
        row = {
            "code": self.code,
            "name": self.name,
            "grade": self.grade,
            "score": round(self.score, 3),
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "qty": self.qty,
            "initial_stop": self.initial_stop,
            "risk_per_share": self.risk_per_share,
            "risk_amount": round(self.risk_amount, 2),
            "net_pnl": round(self.net_pnl, 2),
            "pnl_pct": round(self.pnl_pct, 6),
            "r_multiple": round(self.r_multiple, 4),
            "gross_r": round(self.gross_r, 4),
            "mae_r": round(self.mae_r, 4),
            "mfe_r": round(self.mfe_r, 4),
            "hold_bars": self.hold_bars,
            "hold_minutes": round(self.hold_minutes, 2),
            "exit_reason": self.exit_reason,
            "entry_fee": round(self.entry_fee, 2),
            "sell_fee": round(self.sell_fee, 2),
            "tax": round(self.tax, 2),
            "partial_qty": self.partial_qty,
            "partial_pnl": round(self.partial_pnl, 2),
            "feature_mode": self.feature_mode,
            "signal_ts": self.signal_ts,
            "deferred_id": self.deferred_id,
            "deferred_reasons": self.deferred_reasons,
            "counterfactual": int(self.counterfactual),
        }
        return row


@dataclass
class Portfolio:
    cfg: BacktestConfig
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    equity_points: list[tuple[str, float, float, float]] = field(default_factory=list)

    @classmethod
    def create(cls, cfg: BacktestConfig) -> "Portfolio":
        return cls(cfg=cfg, cash=float(cfg.risk.initial_capital))

    def equity(self, prices: dict[str, float]) -> float:
        value = self.cash
        for code, pos in self.positions.items():
            value += pos.qty * prices.get(code, pos.entry_price)
        return value

    def exposure(self, prices: dict[str, float]) -> float:
        return sum(pos.qty * prices.get(code, pos.entry_price) for code, pos in self.positions.items())

    def can_open(self, code: str) -> bool:
        return code not in self.positions and len(self.positions) < self.cfg.risk.max_positions

    def open(
        self,
        intent: EntryIntent,
        entry_price: float,
        entry_ts: str,
        entry_index: int,
        equity_now: float | None = None,
    ) -> Position | None:
        risk_per_share = entry_price - intent.stop
        if risk_per_share <= 0:
            return None
        equity = (
            float(equity_now)
            if equity_now is not None
            else self.equity({code: pos.entry_price for code, pos in self.positions.items()})
        )
        multiplier = max(0.0, intent.multiplier)
        if multiplier <= 0:
            return None
        budget = equity * self.cfg.risk.risk_per_trade * multiplier
        qty = math.floor(budget / risk_per_share)
        max_weight_qty = math.floor(
            (equity * self.cfg.risk.max_position_weight) / entry_price
        )
        cash_qty = math.floor(
            self.cash / (entry_price * (1.0 + self.cfg.risk.commission))
        )
        qty = min(qty, max_weight_qty, cash_qty)
        if qty < 1:
            return None
        notional = qty * entry_price
        entry_fee = notional * self.cfg.risk.commission
        self.cash -= notional + entry_fee
        pos = Position(
            code=intent.code,
            name=intent.name,
            qty=float(qty),
            original_qty=float(qty),
            entry_price=entry_price,
            entry_ts=entry_ts,
            entry_index=entry_index,
            stop=intent.stop,
            initial_stop=intent.stop,
            risk_per_share=risk_per_share,
            risk_amount=qty * risk_per_share,
            grade=intent.grade,
            score=intent.score,
            entry_fee=entry_fee,
            signal_ts=intent.signal_ts,
            feature_mode=intent.filter_snapshot.get("feature_mode", "bar"),
            deferred_id=intent.filter_snapshot.get("deferred_id", ""),
            deferred_reasons=intent.filter_snapshot.get("deferred_reasons", ""),
            highest=entry_price,
            lowest=entry_price,
        )
        self.positions[intent.code] = pos
        return pos

    def sell(
        self,
        pos: Position,
        qty: float,
        price: float,
        ts: str,
        index: int,
        reason: str,
    ) -> Trade | None:
        qty = min(float(qty), pos.qty)
        if qty <= 0:
            return None
        proceeds = qty * price
        sell_fee = proceeds * self.cfg.risk.commission
        tax = proceeds * self.cfg.risk.tax
        self.cash += proceeds - sell_fee - tax
        pos.qty -= qty
        pos.partial_qty += qty
        pos.partial_proceeds += proceeds
        pos.partial_costs += sell_fee + tax
        pos.partial_sell_fee += sell_fee
        pos.partial_tax += tax

        if pos.qty > 1e-9:
            # Partial take-profit: keep the position open.
            pos.tp_done = True
            if self.cfg.exits.tp_move_stop_to_entry:
                pos.stop = max(pos.stop, pos.entry_price)
            return None

        # Fully closed.
        gross = pos.partial_proceeds - pos.entry_price * pos.original_qty
        costs = pos.entry_fee + pos.partial_costs
        net = gross - costs
        pnl_pct = (
            net / (pos.entry_price * pos.original_qty)
            if pos.entry_price * pos.original_qty > 0
            else 0.0
        )
        r_multiple = net / pos.risk_amount if pos.risk_amount > 0 else 0.0
        gross_r = (
            (pos.partial_proceeds / pos.original_qty - pos.entry_price)
            / pos.risk_per_share
            if pos.original_qty > 0 and pos.risk_per_share > 0
            else 0.0
        )
        hold_minutes = (
            (ts_to_datetime(ts) - ts_to_datetime(pos.entry_ts)).total_seconds() / 60.0
        )
        trade = Trade(
            code=pos.code,
            name=pos.name,
            grade=pos.grade,
            score=pos.score,
            entry_ts=pos.entry_ts,
            exit_ts=ts,
            entry_price=pos.entry_price,
            exit_price=price,
            qty=pos.original_qty,
            initial_stop=pos.initial_stop,
            risk_per_share=pos.risk_per_share,
            risk_amount=pos.risk_amount,
            net_pnl=net,
            pnl_pct=pnl_pct,
            r_multiple=r_multiple,
            gross_r=gross_r,
            mae_r=pos.mae_r,
            mfe_r=pos.mfe_r,
            hold_bars=max(1, index - pos.entry_index),
            hold_minutes=hold_minutes,
            exit_reason=reason,
            entry_fee=pos.entry_fee,
            sell_fee=pos.partial_sell_fee,
            tax=pos.partial_tax,
            partial_qty=pos.partial_qty,
            partial_pnl=pos.partial_proceeds - pos.entry_price * pos.partial_qty,
            feature_mode=pos.feature_mode,
            signal_ts=pos.signal_ts,
            deferred_id=pos.deferred_id,
            deferred_reasons=pos.deferred_reasons,
        )
        self.trades.append(trade)
        del self.positions[pos.code]
        return trade

    def force_close_all(self, prices: dict[str, float], ts: str, reason: str = "X_END") -> None:
        for code in list(self.positions):
            pos = self.positions[code]
            self.sell(pos, pos.qty, prices.get(code, pos.entry_price), ts, pos.entry_index, reason)
