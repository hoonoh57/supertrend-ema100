"""Feature percentiles at signal events, split by feature mode.

Usage:
    python tools/feature_percentiles.py runs/latest/signals.csv --kinds T1,REARM,ENTRY
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict

COLUMNS = ("rti_3", "accel", "buy_ratio", "er_tick", "d_value", "ext_value")
PCTS = (0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def pct(data: list[float], percentile: float) -> float:
    index = (len(data) - 1) * percentile
    lo, hi = math.floor(index), math.ceil(index)
    return data[lo] + (data[hi] - data[lo]) * (index - lo)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--kinds", default="T1,REARM,ENTRY")
    args = parser.parse_args()
    kinds = {kind.strip() for kind in args.kinds.split(",") if kind.strip()}

    groups: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    with open(args.path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if kinds and row.get("kind") not in kinds:
                continue
            mode = row.get("feature_mode") or "?"
            for column in COLUMNS:
                try:
                    value = float(row.get(column) or "")
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    groups[mode][column].append(value)

    for mode, columns in groups.items():
        print(f"\n[feature_mode={mode}]")
        header = " ".join(f"P{int(p * 100):>3}".rjust(8) for p in PCTS)
        print(f"{'feature':<10} {'n':>6} {header}")
        for column in COLUMNS:
            values = sorted(columns.get(column, []))
            if len(values) < 5:
                continue
            percentiles = " ".join(f"{pct(values, p):8.3f}" for p in PCTS)
            print(f"{column:<10} {len(values):>6} {percentiles}")


if __name__ == "__main__":
    main()
