"""Plain data records shared by the data, indicator and backtest layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def normalize_ts(value: Any, digits: int = 12) -> str:
    """Normalize a Kiwoom date/time to YYYYMMDDHHMM (or YYYYMMDDHHMMSS)."""
    raw = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(raw) >= 14:
        return raw[:14] if digits >= 14 else raw[:12]
    if len(raw) == 12:
        return raw
    if len(raw) == 8:
        return raw + "0000"
    return raw.zfill(12)[:12]


@dataclass(slots=True)
class Bar:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float
    # Tick-derived fields.  None means "not measured" (bar-proxy mode).
    n_ticks: float | None = None
    buy_vol: float | None = None
    sell_vol: float | None = None
    path_len: float | None = None
    p_first: float | None = None
    p_last: float | None = None
    vi_flag: bool = False

    @property
    def day(self) -> str:
        return self.ts[:8]

    @property
    def hhmm(self) -> str:
        return self.ts[8:12]

    @property
    def minute_of_day(self) -> int:
        return int(self.hhmm[:2]) * 60 + int(self.hhmm[2:4])

    @property
    def has_tick_fields(self) -> bool:
        return self.n_ticks is not None and self.buy_vol is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Bar":
        def opt(key: str) -> float | None:
            value = row.get(key)
            if value is None or value == "" or str(value).lower() == "nan":
                return None
            return _f(value)

        return cls(
            ts=str(row["ts"]),
            open=_f(row["open"]),
            high=_f(row["high"]),
            low=_f(row["low"]),
            close=_f(row["close"]),
            volume=_f(row["volume"]),
            value=_f(row.get("value")),
            n_ticks=opt("n_ticks"),
            buy_vol=opt("buy_vol"),
            sell_vol=opt("sell_vol"),
            path_len=opt("path_len"),
            p_first=opt("p_first"),
            p_last=opt("p_last"),
            vi_flag=str(row.get("vi_flag", "")).lower() in ("1", "true", "yes"),
        )


@dataclass(slots=True)
class DailyBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DailyBar":
        return cls(
            date=str(row["date"])[:8],
            open=_f(row["open"]),
            high=_f(row["high"]),
            low=_f(row["low"]),
            close=_f(row["close"]),
            volume=_f(row["volume"]),
            value=_f(row["value"]),
        )


@dataclass(slots=True)
class StockInfo:
    code: str
    name: str = ""
    market: str = ""
    shares: float = 0.0
    last_price: float = 0.0
    audit_info: str = ""
    state: str = ""
    reg_day: str = ""
    nxt_enable: bool = False
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "StockInfo":
        return cls(
            code=str(row.get("code", "")).zfill(6),
            name=str(row.get("name", "")),
            market=str(row.get("market", "")),
            shares=_f(row.get("shares")),
            last_price=_f(row.get("last_price")),
            audit_info=str(row.get("audit_info", "")),
            state=str(row.get("state", "")),
            reg_day=str(row.get("reg_day", "")),
            nxt_enable=bool(row.get("nxt_enable", False)),
            kind=str(row.get("kind", "")),
        )


@dataclass(slots=True)
class Tick:
    ts: str  # YYYYMMDDHHMMSS
    price: float
    volume: float

    @property
    def day(self) -> str:
        return self.ts[:8]

    @property
    def minute_ts(self) -> str:
        return self.ts[:12]


class Timestamps:
    """Small helpers for HH:MM strings."""

    @staticmethod
    def to_minutes(hhmm: str) -> int:
        text = "".join(ch for ch in str(hhmm) if ch.isdigit()).zfill(4)
        return int(text[:2]) * 60 + int(text[2:4])

    @staticmethod
    def from_minutes(minutes: int) -> str:
        return f"{minutes // 60:02d}{minutes % 60:02d}"

    @staticmethod
    def bar_minutes(ts: str) -> int:
        text = ts[8:12] if len(ts) >= 12 else "0000"
        return int(text[:2]) * 60 + int(text[2:4])
