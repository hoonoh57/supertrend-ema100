"""Local CSV cache for daily and minute bars.

The Kiwoom chart API is rate limited to roughly one call/second per TR, so a
backtest run reuses everything fetched previously.  The cache is intentionally
plain CSV: inspectable, diffable and dependency-free.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Callable

from ..kiwoom.client import KiwoomClient
from ..kiwoom.models import Bar, DailyBar

BAR_FIELDS = [
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "n_ticks",
    "buy_vol",
    "sell_vol",
    "path_len",
    "p_first",
    "p_last",
    "vi_flag",
]
DAILY_FIELDS = ["date", "open", "high", "low", "close", "volume", "value"]


class BarCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, kind: str, interval: int = 1) -> Path:
        safe = "".join(ch for ch in symbol if ch.isalnum() or ch in "-_")
        if kind == "minute":
            name = f"{safe}_m{interval}.csv"
        else:
            name = f"{safe}_{kind}.csv"
        folder = self.root / "bars"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / name

    # --------------------------------------------------------------- minute
    def load_minutes(self, symbol: str, interval: int = 1) -> list[Bar]:
        path = self._path(symbol, "minute", interval)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as fh:
            return [Bar.from_dict(row) for row in csv.DictReader(fh)]

    def save_minutes(self, symbol: str, bars: list[Bar], interval: int = 1) -> Path:
        path = self._path(symbol, "minute", interval)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=BAR_FIELDS)
            writer.writeheader()
            for bar in bars:
                writer.writerow(
                    {
                        "ts": bar.ts,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "value": bar.value,
                        "n_ticks": "" if bar.n_ticks is None else bar.n_ticks,
                        "buy_vol": "" if bar.buy_vol is None else bar.buy_vol,
                        "sell_vol": "" if bar.sell_vol is None else bar.sell_vol,
                        "path_len": "" if bar.path_len is None else bar.path_len,
                        "p_first": "" if bar.p_first is None else bar.p_first,
                        "p_last": "" if bar.p_last is None else bar.p_last,
                        "vi_flag": int(bar.vi_flag),
                    }
                )
        return path

    def get_minutes(
        self,
        client: KiwoomClient,
        symbol: str,
        end_date: str,
        until_date: str,
        interval: int = 1,
        force_refresh: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> list[Bar]:
        cached = [] if force_refresh else self.load_minutes(symbol, interval)
        cached = [b for b in cached if b.ts[:8] <= end_date]
        need_fetch = (
            force_refresh
            or not cached
            or cached[0].ts[:8] > until_date
            or cached[-1].ts[:8] < end_date
        )
        fetched: list[Bar] = []
        if need_fetch:
            fetched = client.fetch_minutes(
                symbol,
                end_date=end_date,
                until_date=until_date,
                interval=interval,
                progress=progress,
            )
            merged = {b.ts: b for b in cached}
            for bar in fetched:
                merged[bar.ts] = bar
            cached = sorted(merged.values(), key=lambda b: b.ts)
            self.save_minutes(symbol, cached, interval)
        return [b for b in cached if until_date <= b.ts[:8] <= end_date]

    # ---------------------------------------------------------------- daily
    def load_daily(self, symbol: str) -> list[DailyBar]:
        path = self._path(symbol, "daily")
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as fh:
            return [DailyBar.from_dict(row) for row in csv.DictReader(fh)]

    def save_daily(self, symbol: str, bars: list[DailyBar]) -> Path:
        path = self._path(symbol, "daily")
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=DAILY_FIELDS)
            writer.writeheader()
            for bar in bars:
                writer.writerow(
                    {
                        "date": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "value": bar.value,
                    }
                )
        return path

    def get_daily(
        self,
        client: KiwoomClient,
        symbol: str,
        end_date: str,
        until_date: str,
        force_refresh: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> list[DailyBar]:
        cached = [] if force_refresh else self.load_daily(symbol)
        cached = [b for b in cached if b.date <= end_date]
        need_fetch = (
            force_refresh
            or not cached
            or cached[0].date > until_date
            or cached[-1].date < end_date
        )
        if need_fetch:
            fetched = client.fetch_daily(symbol, end_date=end_date, until_date=until_date)
            merged = {b.date: b for b in cached}
            for bar in fetched:
                merged[bar.date] = bar
            cached = sorted(merged.values(), key=lambda b: b.date)
            self.save_daily(symbol, cached)
            if progress:
                progress(f"[{symbol}] daily bars: {len(cached)}")
        return [b for b in cached if until_date <= b.date <= end_date]


def read_meta(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
