"""Report writers: CSV, JSON, text summary and a dependency-free SVG plot."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from ..strategy.engine import BacktestResult
from ..strategy.portfolio import Trade

SIGNAL_FIELDS = [
    "ts",
    "code",
    "name",
    "kind",
    "state_from",
    "state_to",
    "reasons",
    "checks",
    "score",
    "grade",
    "close",
    "d_value",
    "rti_1",
    "rti_3",
    "rti_10",
    "accel",
    "buy_ratio",
    "er_tick",
    "atv_ratio",
    "tov",
    "vwap",
    "ema",
    "st",
    "atr",
    "day_ret",
    "baseline_ready",
    "feature_mode",
    "note",
]


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "-"
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _signal_row(event) -> dict[str, Any]:
    row = asdict(event)
    row["reasons"] = "|".join(event.reasons)
    row["checks"] = "|".join(f"{k}={int(v)}" for k, v in sorted(event.checks.items()))
    return {key: row.get(key, "") for key in SIGNAL_FIELDS}


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _equity_rows(
    points: Iterable[tuple[str, float, float, float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    peak = 0.0
    for ts, equity, cash, exposure in points:
        peak = max(peak, equity)
        drawdown = (equity / peak - 1.0) if peak > 0 else 0.0
        rows.append(
            {
                "ts": ts,
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "exposure": round(exposure, 2),
                "drawdown": round(drawdown, 6),
            }
        )
    return rows


def _write_svg(path: Path, points: list[tuple[str, float, float, float]], initial: float) -> bool:
    daily: dict[str, float] = {}
    for ts, equity, _cash, _exposure in points:
        daily[ts[:8]] = equity
    series = sorted(daily.items())
    if len(series) < 2:
        return False
    values = [v for _d, v in series]
    lo = min(min(values), initial)
    hi = max(max(values), initial)
    span = hi - lo or 1.0
    width, height = 960, 320
    left, right, top, bottom = 70, 20, 20, 40
    plot_w = width - left - right
    plot_h = height - top - bottom

    def px(i: int) -> float:
        return left + plot_w * i / (len(series) - 1)

    def py(value: float) -> float:
        return top + plot_h * (1.0 - (value - lo) / span)

    poly = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, (_d, v) in enumerate(series))
    base_y = py(initial)
    first, last = values[0], values[-1]
    colour = "#1a7f37" if last >= initial else "#b42318"
    step = max(1, len(series) // 6)
    labels = []
    for i in range(0, len(series), step):
        labels.append(
            f'<text x="{px(i):.1f}" y="{height - 12}" text-anchor="middle" '
            f'font-size="11" fill="#57606a">{series[i][0][4:6]}/{series[i][0][6:8]}</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{left}" y="{top - 4}" font-size="12" fill="#57606a">Equity: {first:,.0f} → {last:,.0f}</text>
  <line x1="{left}" y1="{base_y:.1f}" x2="{width - right}" y2="{base_y:.1f}" stroke="#8c959f" stroke-dasharray="4 4" stroke-width="1"/>
  <polyline fill="none" stroke="{colour}" stroke-width="2" points="{poly}"/>
  <text x="8" y="{py(hi) + 4:.1f}" font-size="11" fill="#57606a">{hi:,.0f}</text>
  <text x="8" y="{py(lo) + 4:.1f}" font-size="11" fill="#57606a">{lo:,.0f}</text>
  {''.join(labels)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    return True


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


def _summary(result: BacktestResult, metrics: dict[str, Any]) -> str:
    overall = metrics["overall"]
    equity = metrics["equity"]
    cf = metrics["counterfactual_summary"]
    lines: list[str] = []
    add = lines.append

    add("Supertrend-EMA100 backtest")
    add("=" * 78)
    data = metrics["data"]
    add(f"Period          : {data['start_date']} ~ {data['end_date']} ({data['trading_dates']} trading days)")
    add(f"Symbols         : {', '.join(data['symbols'])}")
    modes = ", ".join(f"{k}={v}" for k, v in data["feature_modes"].items())
    add(f"Feature mode    : {modes}")
    add(f"Selection       : {result.cfg.selection}   Score enabled: {result.cfg.score.enabled}")
    add("")
    add("Performance")
    add("-" * 78)
    add(f"Trades          : {overall['trades']:,}   win rate {_fmt(overall['win_rate'] and overall['win_rate'] * 100, 1)}%")
    add(f"Avg R / PF      : {_fmt(overall['avg_r'], 3)} R / {_fmt(overall['profit_factor'], 2)}  (gross {_fmt(overall['avg_gross_r'], 3)} R)")
    add(f"Expectancy      : {_fmt(overall['expectancy_r'], 3)} R per trade")
    add(f"Net PnL         : {_fmt(overall['net_pnl'], 0)} KRW")
    add(f"Avg hold        : {_fmt(overall['avg_hold_minutes'], 1)} min   MAE {_fmt(overall['avg_mae_r'], 2)} R   MFE {_fmt(overall['avg_mfe_r'], 2)} R")
    add(f"Final equity    : {_fmt(equity['final_equity'], 0)} KRW ({_fmt((equity['total_return'] or 0) * 100, 2)}%)")
    add(f"Sharpe / Sortino: {_fmt(equity['sharpe'], 2)} / {_fmt(equity['sortino'], 2)}")
    add(f"Max drawdown    : {_fmt((equity['max_drawdown_pct'] or 0) * 100, 2)}% ({_fmt(equity['max_drawdown'], 0)} KRW)")
    add(f"Immediate-entry counterfactual: {cf['trades']:,} trades, avg {_fmt(cf['avg_r'], 3)} R")
    add("")
    add("Signals")
    add("-" * 78)
    add("  " + "   ".join(f"{k}={v:,}" for k, v in metrics["signals"].items()))
    add("")

    add("By exit reason")
    add("-" * 78)
    rows = []
    for name, stats in metrics["by_exit_reason"].items():
        rows.append(
            [
                name,
                str(stats["trades"]),
                _fmt(stats["win_rate"] and stats["win_rate"] * 100, 1) + "%",
                _fmt(stats["avg_r"], 3),
                _fmt(stats["net_pnl"], 0),
            ]
        )
    add(_table(["reason", "n", "win%", "avgR", "net KRW"], rows) if rows else "  (no trades)")
    add("")

    add("By score grade")
    add("-" * 78)
    rows = []
    for name, stats in metrics["by_grade"].items():
        rows.append(
            [
                name,
                str(stats["trades"]),
                _fmt(stats["win_rate"] and stats["win_rate"] * 100, 1) + "%",
                _fmt(stats["avg_r"], 3),
                _fmt(stats["net_pnl"], 0),
            ]
        )
    add(_table(["grade", "n", "win%", "avgR", "net KRW"], rows) if rows else "  (no trades)")
    add("")

    add("By entry hour")
    add("-" * 78)
    rows = []
    for name, stats in metrics["by_entry_hour"].items():
        rows.append(
            [
                name,
                str(stats["trades"]),
                _fmt(stats["win_rate"] and stats["win_rate"] * 100, 1) + "%",
                _fmt(stats["avg_r"], 3),
            ]
        )
    add(_table(["window", "n", "win%", "avgR"], rows) if rows else "  (no trades)")
    add("")

    add("Counterfactual per delay filter (plan 6.3)")
    add("-" * 78)
    rows = []
    for row in metrics["counterfactual_filters"]:
        rows.append(
            [
                row["filter"],
                str(row["deferred"]),
                _fmt(row["immediate_avg_r"], 3),
                _fmt(row["rearm_rate"] * 100, 1) + "%",
                _fmt(row["rearmed_avg_r"], 3),
                _fmt(row["net_contribution_r"], 3),
            ]
        )
    add(
        _table(["filter", "deferred", "immR", "rearm%", "rearmR", "contribR"], rows)
        if rows
        else "  (no deferred signals)"
    )
    add("")

    ic = metrics["score_ic_entry"]
    add("Score validation (entry signals)")
    add("-" * 78)
    add(
        f"IC 15m {_fmt(ic['ic_15m'], 3)} (n={ic['n_15m']})   "
        f"IC 30m {_fmt(ic['ic_30m'], 3)} (n={ic['n_30m']})   "
        f"decile monotonicity {_fmt(ic['decile_monotonicity_15m'], 3)}"
    )
    if ic["deciles_15m"]:
        rows = [
            [
                str(d["decile"]),
                str(d["n"]),
                _fmt(d["avg_score"], 1),
                _fmt((d["avg_forward_return"] or 0) * 100, 3) + "%",
                _fmt(d["win_rate"] * 100, 1) + "%",
            ]
            for d in ic["deciles_15m"]
        ]
        add(_table(["decile", "n", "score", "fwd15", "win%"], rows))
    add("")

    if result.warnings:
        add("Warnings")
        add("-" * 78)
        for warning in result.warnings:
            add(f"  - {warning}")
        add("")
    add("Files: trades.csv, signals.csv, counterfactual.csv, virtual_trades.csv,")
    add("       equity.csv, metrics.json, config.json, summary.txt, equity.svg")
    return "\n".join(lines)


def write_report(
    result: BacktestResult,
    metrics: dict[str, Any],
    out_dir: str | Path,
    *,
    plot: bool = False,
) -> dict[str, str]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    trades_path = root / "trades.csv"
    trade_rows = [t.to_row() for t in result.trades]
    trade_fields = list(Trade.__dataclass_fields__.keys())
    # to_row() names the extra counterfactual flag; keep the same order/fields.
    _write_csv(trades_path, list(trade_rows[0].keys()) if trade_rows else trade_fields, trade_rows)
    written["trades"] = str(trades_path)

    virtual_path = root / "virtual_trades.csv"
    virtual_rows = [t.to_row() for t in result.virtual_trades]
    _write_csv(
        virtual_path,
        list(virtual_rows[0].keys()) if virtual_rows else trade_fields,
        virtual_rows,
    )
    written["virtual_trades"] = str(virtual_path)

    signals_path = root / "signals.csv"
    _write_csv(signals_path, SIGNAL_FIELDS, (_signal_row(e) for e in result.events))
    written["signals"] = str(signals_path)

    cf_path = root / "counterfactual.csv"
    cf_rows = metrics["counterfactual_filters"]
    cf_fields = (
        list(cf_rows[0].keys())
        if cf_rows
        else [
            "filter",
            "deferred",
            "immediate_trades",
            "immediate_avg_r",
            "immediate_win_rate",
            "immediate_net_pnl",
            "rearmed",
            "rearm_rate",
            "rearm_not_triggered_ratio",
            "rearmed_avg_r",
            "rearmed_win_rate",
            "rearmed_net_pnl",
            "net_contribution_r",
        ]
    )
    _write_csv(cf_path, cf_fields, cf_rows)
    written["counterfactual"] = str(cf_path)

    equity_path = root / "equity.csv"
    _write_csv(
        equity_path,
        ["ts", "equity", "cash", "exposure", "drawdown"],
        _equity_rows(result.equity_points),
    )
    written["equity"] = str(equity_path)

    metrics_path = root / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    written["metrics"] = str(metrics_path)

    config_path = root / "config.json"
    config_path.write_text(
        json.dumps(result.cfg.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    written["config"] = str(config_path)

    summary_path = root / "summary.txt"
    summary_path.write_text(_summary(result, metrics), encoding="utf-8")
    written["summary"] = str(summary_path)

    if plot and _write_svg(
        root / "equity.svg", list(result.equity_points), result.cfg.risk.initial_capital
    ):
        written["plot"] = str(root / "equity.svg")
    return written
