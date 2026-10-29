"""Performance metrics (plan 6.3, 6.4, 7.6, 8.1).

Everything is computed from the backtest result only, so the same functions
work for paper trading logs once they are converted to the same records.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Iterable, Sequence

from ..strategy.engine import BacktestResult
from ..strategy.portfolio import Trade
from ..data.series import SymbolSeries


# ------------------------------------------------------------------ helpers
def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _mean(values: Sequence[float]) -> float | None:
    data = [float(v) for v in values if _finite(v)]
    return sum(data) / len(data) if data else None


def _percentile(values: Sequence[float], p: float) -> float | None:
    data = sorted(float(v) for v in values if _finite(v))
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    index = (len(data) - 1) * p
    lo = int(math.floor(index))
    hi = int(math.ceil(index))
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (index - lo)


def _std(values: Sequence[float]) -> float | None:
    data = [float(v) for v in values if _finite(v)]
    if len(data) < 2:
        return None
    return statistics.stdev(data)


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks for ties (1-based)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if _finite(x) and _finite(y)
    ]
    if len(pairs) < 5:
        return None
    x = _ranks([p[0] for p in pairs])
    y = _ranks([p[1] for p in pairs])
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def _safe_div(num: float, den: float) -> float | None:
    return num / den if den not in (0, 0.0) else None


# -------------------------------------------------------------- trade stats
def trade_stats(trades: Sequence[Trade]) -> dict[str, object]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "avg_r": None,
            "avg_gross_r": None,
            "median_r": None,
            "profit_factor": None,
            "expectancy_r": None,
            "net_pnl": 0.0,
            "avg_pnl_pct": None,
            "avg_hold_minutes": None,
            "avg_mae_r": None,
            "avg_mfe_r": None,
            "r_std": None,
            "r_p10": None,
            "r_p90": None,
            "mae_p50": None,
            "mfe_p50": None,
        }
    r = [t.r_multiple for t in trades]
    wins = [v for v in r if v > 0]
    losses = [v for v in r if v <= 0]
    gross_profit = sum(max(0.0, t.net_pnl) for t in trades)
    gross_loss = -sum(min(0.0, t.net_pnl) for t in trades)
    pf = gross_profit / gross_loss if gross_loss > 0 else None
    mae = [t.mae_r for t in trades]
    mfe = [t.mfe_r for t in trades]
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n,
        "avg_r": _mean(r),
        "avg_gross_r": _mean([t.gross_r for t in trades]),
        "median_r": statistics.median(r),
        "profit_factor": pf,
        "expectancy_r": _mean(r),
        "net_pnl": sum(t.net_pnl for t in trades),
        "avg_pnl_pct": _mean([t.pnl_pct for t in trades]),
        "avg_hold_minutes": _mean([t.hold_minutes for t in trades]),
        "avg_mae_r": _mean(mae),
        "avg_mfe_r": _mean(mfe),
        "r_std": _std(r),
        "r_p10": _percentile(r, 0.10),
        "r_p90": _percentile(r, 0.90),
        "mae_p50": _percentile(mae, 0.50),
        "mfe_p50": _percentile(mfe, 0.50),
    }


# ------------------------------------------------------------- equity stats
def _daily_equity(points: Sequence[tuple[str, float, float, float]]) -> list[tuple[str, float]]:
    by_day: dict[str, float] = {}
    for ts, equity, _cash, _exposure in points:
        by_day[ts[:8]] = float(equity)
    return sorted(by_day.items())


def equity_stats(
    points: Sequence[tuple[str, float, float, float]], initial_capital: float
) -> dict[str, object]:
    daily = _daily_equity(points)
    if not daily:
        return {
            "initial_capital": initial_capital,
            "final_equity": initial_capital,
            "total_return": 0.0,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "daily_returns": 0,
        }
    final = daily[-1][1]
    returns: list[float] = []
    prev = initial_capital
    for _day, equity in daily:
        if prev > 0:
            returns.append(equity / prev - 1.0)
        prev = equity
    mean = _mean(returns) or 0.0
    sd = _std(returns)
    downside = [v for v in returns if v < 0]
    dsd = _std(downside)
    sharpe = (mean / sd * math.sqrt(252)) if sd and sd > 0 else None
    sortino = (mean / dsd * math.sqrt(252)) if dsd and dsd > 0 else None

    peak = initial_capital
    max_dd = 0.0
    max_dd_pct = 0.0
    for _day, equity in daily:
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak if peak > 0 else 0.0
    return {
        "initial_capital": initial_capital,
        "final_equity": final,
        "total_return": final / initial_capital - 1.0 if initial_capital > 0 else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "daily_returns": len(returns),
    }


# ------------------------------------------------------------------ buckets
def _hour_bucket(ts: str) -> str:
    hhmm = ts[8:12]
    if len(hhmm) < 4:
        return "unknown"
    minutes = int(hhmm[:2]) * 60 + int(hhmm[2:4])
    if minutes < 9 * 60 + 30:
        return "09:00-09:30"
    if minutes < 11 * 60:
        return "09:30-11:00"
    if minutes < 15 * 60 + 15:
        return "11:00-15:15"
    return "after-15:15"


def _group_stats(trades: Iterable[Trade], key) -> dict[str, dict[str, object]]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[str(key(trade))].append(trade)
    return {name: trade_stats(items) for name, items in sorted(groups.items())}


# ---------------------------------------------------------------- score IC
def _forward_return(series: SymbolSeries, i: int, horizon: int) -> float | None:
    j = i + horizon
    if j < 0 or j >= len(series.bars):
        return None
    if series.bars[j].day != series.bars[i].day:
        return None
    base = series.bars[i].close
    if base <= 0:
        return None
    return series.bars[j].close / base - 1.0


def score_ic(result: BacktestResult, kinds: tuple[str, ...] = ("ENTRY",)) -> dict[str, object]:
    rows: list[tuple[float, float | None, float | None]] = []
    for event in result.events:
        if event.kind not in kinds:
            continue
        series = result.data.series.get(event.code)
        if series is None:
            continue
        index = series.index_by_ts.get(event.ts)
        if index is None:
            continue
        rows.append(
            (
                event.score,
                _forward_return(series, index, 15),
                _forward_return(series, index, 30),
            )
        )
    scores = [r[0] for r in rows]
    fwd15 = [r[1] for r in rows]
    fwd30 = [r[2] for r in rows]
    finite15 = [(s, f) for s, f in zip(scores, fwd15) if _finite(s) and _finite(f)]
    finite30 = [(s, f) for s, f in zip(scores, fwd30) if _finite(s) and _finite(f)]

    def deciles(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
        if len(pairs) < 10:
            return []
        ordered = sorted(pairs, key=lambda p: p[0])
        bins = min(10, max(2, len(ordered) // 5))
        out: list[dict[str, object]] = []
        for b in range(bins):
            lo = b * len(ordered) // bins
            hi = (b + 1) * len(ordered) // bins
            chunk = ordered[lo:hi]
            if not chunk:
                continue
            out.append(
                {
                    "decile": b + 1,
                    "n": len(chunk),
                    "avg_score": _mean([c[0] for c in chunk]),
                    "avg_forward_return": _mean([c[1] for c in chunk]),
                    "win_rate": sum(1 for c in chunk if c[1] > 0) / len(chunk),
                }
            )
        return out

    d15 = deciles(finite15)
    d15_monotonic = None
    if len(d15) >= 3:
        d15_monotonic = spearman(
            [float(d["decile"]) for d in d15],
            [float(d["avg_forward_return"] or 0.0) for d in d15],
        )
    return {
        "kind": list(kinds),
        "signals": len(rows),
        "ic_15m": spearman([s for s, _ in finite15], [f for _, f in finite15]),
        "ic_30m": spearman([s for s, _ in finite30], [f for _, f in finite30]),
        "n_15m": len(finite15),
        "n_30m": len(finite30),
        "deciles_15m": d15,
        "decile_monotonicity_15m": d15_monotonic,
    }


# --------------------------------------------------------- counterfactuals
def counterfactual_table(result: BacktestResult) -> list[dict[str, object]]:
    """Plan 6.3: per-filter deferred vs immediate-entry performance."""
    virtuals = list(result.virtual_trades)
    by_id = {t.deferred_id: t for t in result.trades if t.deferred_id}
    reasons: set[str] = set()
    for trade in virtuals:
        reasons.update(r for r in trade.deferred_reasons.split("|") if r)

    rows: list[dict[str, object]] = []
    groups: list[tuple[str, list[Trade]]] = [("ALL", virtuals)]
    groups.extend((reason, [t for t in virtuals if reason in t.deferred_reasons.split("|")]) for reason in sorted(reasons))
    for reason, group in groups:
        if not group:
            continue
        vids = {t.deferred_id for t in group}
        rearmed = [by_id[vid] for vid in vids if vid in by_id]
        virtual_stats = trade_stats(group)
        rearm_stats = trade_stats(rearmed)
        rearm_rate = len(rearmed) / len(group) if group else 0.0
        virtual_r = virtual_stats["avg_r"]
        rearm_r = rearm_stats["avg_r"]
        contribution = None
        if virtual_r is not None and rearm_r is not None:
            contribution = rearm_rate * float(rearm_r) - float(virtual_r)
        rows.append(
            {
                "filter": reason,
                "deferred": len(group),
                "immediate_trades": virtual_stats["trades"],
                "immediate_avg_r": virtual_r,
                "immediate_win_rate": virtual_stats["win_rate"],
                "immediate_net_pnl": virtual_stats["net_pnl"],
                "rearmed": len(rearmed),
                "rearm_rate": rearm_rate,
                "rearm_not_triggered_ratio": 1.0 - rearm_rate,
                "rearmed_avg_r": rearm_r,
                "rearmed_win_rate": rearm_stats["win_rate"],
                "rearmed_net_pnl": rearm_stats["net_pnl"],
                "net_contribution_r": contribution,
            }
        )
    return rows


# -------------------------------------------------------------- main entry
def compute_metrics(result: BacktestResult) -> dict[str, object]:
    cfg = result.cfg
    trades = list(result.trades)
    virtuals = list(result.virtual_trades)
    events = result.events

    signal_counts: dict[str, int] = defaultdict(int)
    for event in events:
        signal_counts[event.kind] += 1

    by_grade = _group_stats(trades, lambda t: t.grade)
    by_reason = _group_stats(trades, lambda t: t.exit_reason)
    by_hour = _group_stats(trades, lambda t: _hour_bucket(t.entry_ts))
    by_symbol = _group_stats(trades, lambda t: f"{t.name}({t.code})")
    by_feature_mode = _group_stats(trades, lambda t: t.feature_mode)

    series_info = {}
    for code, series in result.data.series.items():
        series_info[code] = {
            "name": series.name,
            "bars": len(series.bars),
            "first_bar": series.bars[0].ts if series.bars else "",
            "last_bar": series.bars[-1].ts if series.bars else "",
            "feature_mode": series.feature_mode,
            "score_mean": _mean([s.score for s in series.scores]),
            "grade_counts": {
                g: sum(1 for s in series.scores if s.grade == g) for g in ("A", "B", "C", "-")
            },
        }

    window_days = [
        d
        for d in result.data.trading_dates
        if result.data.start_date <= d <= result.data.end_date
    ]

    return {
        "config": cfg.to_dict(),
        "data": {
            "symbols": list(result.data.series),
            "trading_dates": len(window_days),
            "trading_dates_total": len(result.data.trading_dates),
            "start_date": result.data.start_date,
            "end_date": result.data.end_date,
            "feature_modes": result.data.feature_modes,
            "series": series_info,
            "warnings": list(result.warnings),
        },
        "overall": trade_stats(trades),
        "equity": equity_stats(result.equity_points, cfg.risk.initial_capital),
        "counterfactual_summary": trade_stats(virtuals),
        "by_grade": by_grade,
        "by_exit_reason": by_reason,
        "by_entry_hour": by_hour,
        "by_symbol": by_symbol,
        "by_feature_mode": by_feature_mode,
        "signals": dict(sorted(signal_counts.items())),
        "score_ic_entry": score_ic(result, kinds=("ENTRY",)),
        "score_ic_t1": score_ic(result, kinds=("T1",)),
        "counterfactual_filters": counterfactual_table(result),
    }
