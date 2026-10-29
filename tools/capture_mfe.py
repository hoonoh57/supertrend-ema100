"""Compare post-capture MFE/MAE by capture-time bucket.

python tools/capture_mfe.py --universe universe.csv --minutes 60
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supertrend_ema100.cli import _make_client  # noqa: E402
from supertrend_ema100.config import BacktestConfig  # noqa: E402
from supertrend_ema100.data.cache import BarCache  # noqa: E402
from supertrend_ema100.data.loader import load_backtest_data  # noqa: E402
from supertrend_ema100.data.universe import (  # noqa: E402
    capture_minute,
    load_universe,
    parse_hhmmss,
    universe_range,
    universe_symbols,
)


def _fmt(seconds: int) -> str:
    return f"{seconds // 3600:02d}{seconds % 3600 // 60:02d}"


def _print_group(label: str, group: list[dict[str, Any]], mfe_hit: float) -> None:
    if not group:
        print(f"{label:<14} {0:>5}")
        return
    mfe = [row["mfe"] for row in group]
    print(
        f"{label:<14} {len(group):>5} {statistics.mean(mfe):8.2%} "
        f"{statistics.median(mfe):8.2%} "
        f"{sum(value >= mfe_hit for value in mfe) / len(group):8.1%} "
        f"{statistics.mean(row['mae'] for row in group):8.2%} "
        f"{statistics.mean(row['ret'] for row in group):8.2%} "
        f"{sum(row['ret'] > 0 for row in group) / len(group):7.1%}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument(
        "--buckets", default="0900,0901,0902,0903,0905,0910,0930,1100,1530"
    )
    parser.add_argument("--mfe-hit", type=float, default=0.03)
    parser.add_argument("--out", default="capture_mfe.csv")
    args = parser.parse_args()
    if args.minutes < 1:
        parser.error("--minutes must be >= 1")
    edges = [parse_hhmmss(value) for value in args.buckets.split(",")]
    if len(edges) < 2 or edges != sorted(set(edges)):
        parser.error("--buckets must contain at least two strictly increasing times")

    universe = load_universe(args.universe, "0000", "2359")
    span = universe_range(universe)
    if span is None:
        print("universe가 비었습니다", file=sys.stderr)
        return 2

    cfg = BacktestConfig()
    cfg.universe.file = args.universe
    cfg.universe.capture_from, cfg.universe.capture_to = "0000", "2359"
    cfg.data.symbols = universe_symbols(universe)
    cfg.data.start, cfg.data.end = span
    cfg.validate()

    with _make_client(cfg) as client:
        infos = client.resolve_symbols(
            cfg.data.symbols, allow_unresolved=cfg.data.allow_unresolved
        )
        data = load_backtest_data(
            client, BarCache(cfg.data.cache_dir), infos, cfg
        )

    rows: list[dict[str, Any]] = []
    for code, series in data.series.items():
        for day, seconds in (series.capture or {}).items():
            start = capture_minute(seconds)
            bars = [
                bar
                for bar in series.bars
                if bar.day == day and bar.minute_of_day >= start
            ][: args.minutes]
            if not bars or bars[0].close <= 0:
                continue
            reference = bars[0].close
            rows.append(
                {
                    "date": day,
                    "code": code,
                    "name": series.name,
                    "capture": _fmt(seconds),
                    "sec": seconds,
                    "ref": reference,
                    "mfe": max(bar.high for bar in bars) / reference - 1,
                    "mae": min(bar.low for bar in bars) / reference - 1,
                    "ret": bars[-1].close / reference - 1,
                }
            )

    header = (
        f"{'capture':<14} {'n':>5} {'MFEavg':>8} {'MFEmed':>8} "
        f"{'MFE>=' + format(args.mfe_hit, '.0%'):>8} {'MAEavg':>8} "
        f"{'RETavg':>8} {'win':>7}"
    )
    print(f"\n[구간별] 포착 후 {args.minutes}분, 기준가=포착 직후 첫 봉 종가\n{header}")
    for lower, upper in zip(edges, edges[1:]):
        _print_group(
            f"{_fmt(lower)}-{_fmt(upper)}",
            [row for row in rows if lower <= row["sec"] < upper],
            args.mfe_hit,
        )
    print(f"\n[누적] {_fmt(edges[0])}부터 해당 시각까지 포착된 전체\n{header}")
    for upper in edges[1:]:
        _print_group(
            f"{_fmt(edges[0])}-{_fmt(upper)}",
            [row for row in rows if edges[0] <= row["sec"] < upper],
            args.mfe_hit,
        )

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "code", "name", "capture", "ref", "mfe", "mae", "ret"]
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (item["date"], item["sec"])):
            writer.writerow({key: row[key] for key in fields})
    print(f"\n[csv] {output} ({len(rows)} symbol-days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
