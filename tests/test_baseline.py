from __future__ import annotations

import unittest

from tests.helpers import make_bars

from supertrend_ema100.config import BaselineConfig
from supertrend_ema100.indicators.tick_strength import BaselineBuilder, compute_tick_features


class BaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = BaselineConfig(
            base_days=5,
            base_smooth=0,
            base_floor=0.5,
            base_min_days=2,
            min_bars_per_day=1,
        )
        self.symbol = "005930"
        self.bars = (
            make_bars("20260102", [100.0] * 10, n_ticks=10)
            + make_bars("20260105", [100.0] * 10, n_ticks=20)
            + make_bars("20260106", [100.0] * 10, n_ticks=100)
        )
        self.builder = BaselineBuilder({self.symbol: self.bars}, self.cfg)

    def test_uses_prior_days_only(self) -> None:
        curve3 = self.builder.build_curve(self.symbol, "20260106")
        self.assertTrue(curve3.ready)
        self.assertFalse(curve3.fallback)
        self.assertEqual(curve3.n_days, 2)
        self.assertAlmostEqual(curve3.ticks[9 * 60 + 1], 15.0)

        # Day 2 only knows day 1; day 3's spike must not leak backwards.
        curve2 = self.builder.build_curve(self.symbol, "20260105")
        self.assertAlmostEqual(curve2.ticks[9 * 60 + 1], 10.0)

    def test_first_day_has_no_baseline(self) -> None:
        curve = self.builder.build_curve(self.symbol, "20260102")
        self.assertFalse(curve.ready)
        self.assertTrue(curve.fallback)
        self.assertEqual(curve.n_days, 0)

    def test_rti_uses_prior_baseline(self) -> None:
        curves = self.builder.build_all()[self.symbol]
        features = compute_tick_features(
            self.bars,
            curves,
            market_cap=1_000_000_000.0,
            feature_mode="tick",
        )
        # Day 3 index 20 is the first bar of 20260106.
        self.assertAlmostEqual(features.rti_1[20], 100.0 / 15.0)
        self.assertAlmostEqual(features.rti_3[22], 300.0 / 45.0)
        self.assertTrue(features.baseline_ready[20])
        self.assertFalse(features.baseline_ready[0])

    def test_bar_mode_proxy_uses_same_trade_size_for_baseline(self) -> None:
        """RTI must not be scaled by assumed_trade_size in bar mode."""
        day1 = make_bars("20260102", [100.0] * 10, volume=1_000.0)
        day2 = make_bars("20260105", [100.0] * 10, volume=1_000.0)
        day3 = make_bars("20260106", [100.0] * 10, volume=2_000.0)
        bars = day1 + day2 + day3
        for trade_size in (1.0, 100.0):
            builder = BaselineBuilder(
                {self.symbol: bars},
                self.cfg,
                assumed_trade_size=trade_size,
            )
            curves = builder.build_all()[self.symbol]
            features = compute_tick_features(
                bars,
                curves,
                market_cap=1_000_000_000.0,
                assumed_trade_size=trade_size,
                feature_mode="bar",
            )
            # Baseline 1,000-unit volume vs current 2,000-unit volume.
            self.assertAlmostEqual(features.rti_1[20], 2.0)
            self.assertAlmostEqual(features.rti_3[22], 2.0)


if __name__ == "__main__":
    unittest.main()
