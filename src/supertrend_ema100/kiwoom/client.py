"""Kiwoom REST chart / stock-info client.

Only public market-data endpoints are used.  No order endpoint is called.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .auth import KiwoomError, KiwoomHttp
from .env import Credentials
from .models import Bar, DailyBar, StockInfo, Tick, normalize_ts

ProgressFn = Callable[[str], None]

CHART_PATH = "/api/dostk/chart"
STOCK_INFO_PATH = "/api/dostk/stkinfo"


def _abs_num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).replace(",", "").strip()
    try:
        return abs(float(text))
    except ValueError:
        return 0.0


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _first_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    preferred = (
        "stk_min_pole_chart_qry",
        "stk_dt_pole_chart_qry",
        "stk_tic_chart_qry",
        "stk_tic_pole_chart_qry",
        "stk_week_pole_chart_qry",
        "stk_month_pole_chart_qry",
        "stk_year_pole_chart_qry",
    )
    for key in preferred:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


@dataclass
class FetchStats:
    requests: int = 0
    pages: int = 0
    rows: int = 0
    oldest: str = ""
    newest: str = ""


class KiwoomClient:
    def __init__(
        self,
        credentials: Credentials,
        cache_dir: str | Path = ".cache",
        verbose: bool = False,
        min_interval: float = 1.08,
    ) -> None:
        self.creds = credentials
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.http = KiwoomHttp(credentials, min_interval=min_interval, verbose=verbose)

    # ------------------------------------------------------------------ util
    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    @staticmethod
    def normalize_code(code: str) -> str:
        text = str(code or "").strip().upper()
        text = re.sub(r"^(A|KRX|KOSPI|KOSDAQ)[-_]?", "", text)
        text = re.sub(r"_(AL|NX)$", "", text)
        text = text.strip()
        if text.isdigit():
            return text.zfill(6)
        return text

    # ---------------------------------------------------------------- daily
    @staticmethod
    def parse_daily_row(row: dict[str, Any]) -> DailyBar | None:
        date = normalize_ts(row.get("dt") or row.get("date"), 8)
        if len(date) < 8:
            return None
        close = _abs_num(row.get("cur_prc") or row.get("close"))
        open_ = _abs_num(row.get("open_pric") or row.get("open"))
        high = _abs_num(row.get("high_pric") or row.get("high"))
        low = _abs_num(row.get("low_pric") or row.get("low"))
        if open_ <= 0:
            open_ = close
        if high <= 0:
            high = max(open_, close)
        if low <= 0:
            low = min(open_, close)
        volume = _abs_num(row.get("trde_qty") or row.get("volume"))
        # ka10081 reports trde_prica in million KRW.
        value = _abs_num(row.get("trde_prica") or row.get("value"))
        if value > 0:
            value *= 1_000_000
        else:
            value = close * volume
        if close <= 0 or high <= 0 or low <= 0:
            return None
        return DailyBar(
            date=date[:8],
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            value=value,
        )

    def fetch_daily(
        self,
        symbol: str,
        end_date: str,
        until_date: str | None = None,
        max_pages: int = 8,
    ) -> list[DailyBar]:
        symbol = self.normalize_code(symbol)
        end_date = "".join(ch for ch in end_date if ch.isdigit())[:8]
        until_date = "".join(ch for ch in (until_date or "" ) if ch.isdigit())[:8] or None
        body = {"stk_cd": symbol, "base_dt": end_date, "upd_stkpc_tp": "1"}
        cont, next_key = "N", ""
        found: dict[str, DailyBar] = {}
        for _ in range(max_pages):
            resp = self.http.request("ka10081", CHART_PATH, body, cont, next_key)
            rows = _first_list(resp.json)
            for row in rows:
                bar = self.parse_daily_row(row)
                if bar and (not until_date or bar.date >= until_date):
                    found[bar.date] = bar
            cont = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if not rows or cont != "Y" or not next_key:
                break
            oldest = min((normalize_ts(r.get("dt"), 8) for r in rows), default="")
            if until_date and oldest and oldest < until_date:
                break
        return sorted(found.values(), key=lambda b: b.date)

    # --------------------------------------------------------------- minute
    @staticmethod
    def parse_minute_row(row: dict[str, Any]) -> Bar | None:
        ts = normalize_ts(row.get("cntr_tm") or row.get("cntg_tm") or row.get("time"), 12)
        if len(ts) < 12:
            return None
        close = _abs_num(row.get("cur_prc") or row.get("close"))
        open_ = _abs_num(row.get("open_pric") or row.get("open"))
        high = _abs_num(row.get("high_pric") or row.get("high"))
        low = _abs_num(row.get("low_pric") or row.get("low"))
        if open_ <= 0:
            open_ = close
        if high <= 0:
            high = max(open_, close)
        if low <= 0:
            low = min(open_, close)
        volume = _abs_num(row.get("trde_qty") or row.get("volume"))
        if close <= 0 or high <= 0 or low <= 0:
            return None
        typical = (high + low + close) / 3.0
        return Bar(
            ts=ts,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            value=typical * volume,
        )

    def fetch_minutes(
        self,
        symbol: str,
        end_date: str,
        until_date: str | None = None,
        interval: int = 1,
        max_pages: int = 200,
        progress: ProgressFn | None = None,
    ) -> list[Bar]:
        symbol = self.normalize_code(symbol)
        end_date = "".join(ch for ch in end_date if ch.isdigit())[:8]
        until_date = "".join(ch for ch in (until_date or "") if ch.isdigit())[:8] or None
        body = {
            "stk_cd": symbol,
            "tic_scope": str(max(1, int(interval))),
            "base_dt": end_date,
            "upd_stkpc_tp": "1",
        }
        cont, next_key = "N", ""
        found: dict[str, Bar] = {}
        stats = FetchStats()
        for page in range(max_pages):
            resp = self.http.request("ka10080", CHART_PATH, body, cont, next_key)
            stats.requests += 1
            stats.pages += 1
            rows = _first_list(resp.json)
            for row in rows:
                bar = self.parse_minute_row(row)
                if bar:
                    found[bar.ts] = bar
            cont = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if progress and rows:
                oldest = min((normalize_ts(r.get("cntr_tm"), 12) for r in rows), default="")
                progress(f"[{symbol}] page {page + 1}: {len(found)} bars, oldest {oldest}")
            if not rows or cont != "Y" or not next_key:
                break
            oldest = min(
                (normalize_ts(r.get("cntr_tm"), 12) for r in rows), default=""
            )
            # Stop once the page goes before the requested day (full day fetched).
            if until_date and oldest and oldest[:8] < until_date:
                break
        bars = sorted(found.values(), key=lambda b: b.ts)
        return bars

    # ----------------------------------------------------------------- tick
    @staticmethod
    def parse_tick_row(row: dict[str, Any]) -> Tick | None:
        ts = normalize_ts(row.get("cntr_tm") or row.get("time"), 14)
        if len(ts) < 14:
            return None
        price = _abs_num(row.get("cur_prc") or row.get("price"))
        volume = _abs_num(row.get("trde_qty") or row.get("volume"))
        if price <= 0:
            return None
        return Tick(ts=ts, price=price, volume=volume)

    def fetch_ticks(self, symbol: str, pages: int = 1) -> list[Tick]:
        """Fetch the most recent tick pages (900 ticks per page).

        The REST tick endpoint does not accept a date and only returns recent
        ticks, so this is a collector helper, not a multi-day backtest source.
        """
        symbol = self.normalize_code(symbol)
        body = {"stk_cd": symbol, "tic_scope": "1", "upd_stkpc_tp": "1"}
        cont, next_key = "N", ""
        found: dict[str, Tick] = {}
        for _ in range(max(1, pages)):
            resp = self.http.request("ka10079", CHART_PATH, body, cont, next_key)
            rows = _first_list(resp.json)
            for row in rows:
                tick = self.parse_tick_row(row)
                if tick:
                    found[tick.ts] = tick
            cont = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if not rows or cont != "Y" or not next_key:
                break
        return sorted(found.values(), key=lambda t: t.ts)

    # ---------------------------------------------------------- stock master
    def _master_cache_path(self) -> Path:
        return self.cache_dir / "stock_master.json"

    def fetch_stock_master(self, force: bool = False, max_age_sec: int = 86_400) -> dict[str, StockInfo]:
        path = self._master_cache_path()
        if not force and path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if time.time() - float(payload.get("asof", 0)) < max_age_sec:
                    return {
                        row["code"]: StockInfo.from_dict(row)
                        for row in payload.get("items", [])
                    }
            except (ValueError, KeyError, OSError):
                pass

        items: dict[str, StockInfo] = {}
        last_error: Exception | None = None
        for mrkt_tp in ("0", "10", "8", "50"):
            try:
                resp = self.http.request("ka10099", STOCK_INFO_PATH, {"mrkt_tp": mrkt_tp})
            except Exception as exc:  # noqa: BLE001 - mock server may not expose a market
                last_error = exc
                continue
            rows = _first_list(resp.json)
            for row in rows:
                code = self.normalize_code(str(row.get("code", "")))
                if len(code) != 6 or code == "000000":
                    continue
                info = StockInfo(
                    code=code,
                    name=str(row.get("name", "")).strip(),
                    market=str(row.get("marketName", "")).strip(),
                    shares=float(_int(row.get("listCount"))),
                    last_price=_abs_num(row.get("lastPrice")),
                    audit_info=str(row.get("auditInfo", "")).strip(),
                    state=str(row.get("state", "")).strip(),
                    reg_day=str(row.get("regDay", "")).strip(),
                    nxt_enable=str(row.get("nxtEnable", "")).upper() == "Y",
                    kind=str(row.get("kind", "")).strip(),
                )
                if info.name:
                    items[code] = info
        if not items:
            if last_error:
                raise KiwoomError(f"종목 마스터 조회 실패: {last_error}")
            raise KiwoomError("종목 마스터가 비어 있습니다.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"asof": time.time(), "items": [v.to_dict() for v in items.values()]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return items

    def resolve_symbols(
        self, inputs: Iterable[str], allow_unresolved: bool = False
    ) -> list[StockInfo]:
        master = self.fetch_stock_master()
        by_name: dict[str, list[StockInfo]] = {}
        for info in master.values():
            by_name.setdefault(re.sub(r"\s+", "", info.name), []).append(info)

        resolved: list[StockInfo] = []
        missing: list[str] = []
        for raw in inputs:
            token = str(raw).strip()
            if not token:
                continue
            code = self.normalize_code(token)
            if re.fullmatch(r"\d{6}", code):
                info = master.get(code)
                resolved.append(info or StockInfo(code=code, name=code))
                continue
            key = re.sub(r"\s+", "", token)
            exact = by_name.get(key, [])
            if len(exact) == 1:
                resolved.append(exact[0])
                continue
            matches = [
                info
                for name, infos in by_name.items()
                if key and (key in name or name in key)
                for info in infos
            ]
            if len(matches) == 1:
                resolved.append(matches[0])
            elif len(matches) > 1:
                sample = ", ".join(f"{m.name}({m.code})" for m in matches[:8])
                raise KiwoomError(f"'{token}' 이름이 여러 종목과 일치합니다: {sample}")
            else:
                missing.append(token)

        if missing:
            if allow_unresolved and all(re.fullmatch(r"\d{6}", self.normalize_code(m)) for m in missing):
                resolved.extend(StockInfo(code=self.normalize_code(m), name=self.normalize_code(m)) for m in missing)
            else:
                raise KiwoomError(
                    "종목을 찾지 못했습니다: "
                    + ", ".join(missing)
                    + " (6자리 코드 또는 정확한 종목명을 사용하세요)"
                )

        # de-duplicate while preserving order
        seen: set[str] = set()
        unique: list[StockInfo] = []
        for info in resolved:
            if info.code in seen:
                continue
            seen.add(info.code)
            unique.append(info)
        return unique

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self.http.session.close()

    def __enter__(self) -> "KiwoomClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
