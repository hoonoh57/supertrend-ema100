"""Regression tests for EXT reference and session-bounded features."""

from __future__ import annotations

import unittest

from supertrend_ema100.config import BacktestConfig, ScoreConfig
from supertrend_ema100.indicators.extension import extension_value, last_up_flip
from supertrend_ema100.indicators.score import compute_score
from supertrend_ema100.indicators.tick_strength import (
    BaselineCurve,
    compute_tick_features,
)

from .helpers import make_bars


def _score(cfg: ScoreConfig, **kwargs):
    base = dict(
        close=100.0,
        vwap=None,
        sigma_eff=None,
        vwap_slope_atr=None,
        above_vwap_ratio=None,
        rti_3=None,
        accel=None,
        buy_ratio=None,
        er_tick=None,
        atv_ratio=None,
        tov=None,
        tov_p50=None,
        tov_p95=None,
        st_line=None,
        atr=None,
        vi_up=None,
    )
    base.update(kwargs)
    return compute_score(cfg, **base)


class DayBoundaryTest(unittest.TestCase):
    def test_feature_windows_do_not_cross_sessions(self):
        bars = make_bars("20260102", [100.0] * 12) + make_bars(
            "20260105", [101.0] * 12
        )
        baseline = BaselineCurve([1.0] * 1440, [1.0] * 1440, 10, False, True)
        features = compute_tick_features(
            bars,
            {"20260102": baseline, "20260105": baseline},
            market_cap=1e9,
            feature_mode="bar",
        )
        first = 12
        for offset in range(4):
            self.assertIsNone(features.buy_ratio_5[first + offset])
            self.assertIsNone(features.er_5[first + offset])
        self.assertIsNotNone(features.buy_ratio_5[first + 4])
        self.assertIsNotNone(features.er_5[first + 4])
        self.assertIsNone(features.rti_3[first])
        self.assertIsNotNone(features.rti_3[first + 2])


class ExtensionConfigTest(unittest.TestCase):
    def test_invalid_extension_reference_is_rejected(self):
        cfg = BacktestConfig()
        cfg.delay.ext_ref = "unknown"
        with self.assertRaisesRegex(ValueError, "delay.ext_ref"):
            cfg.validate()

    def test_negative_fresh_bar_count_is_rejected(self):
        cfg = BacktestConfig()
        cfg.delay.ext_fresh_bars = -1
        with self.assertRaisesRegex(ValueError, "ext_fresh_bars"):
            cfg.validate()


class ExtensionTest(unittest.TestCase):
    direction = [-1, -1, 1, 1, 1]
    st_upper = [0.0, 0.0, 105.0, 104.0, 103.0]

    def test_last_up_flip_obeys_fresh_bar_count(self):
        self.assertEqual(last_up_flip(self.direction, 4, 3), 2)
        self.assertIsNone(last_up_flip(self.direction, 4, 2))
        self.assertEqual(last_up_flip(self.direction, 2, 1), 2)

    def test_breakout_then_st_line(self):
        value, limit, kind = extension_value(
            2,
            106.0,
            2.0,
            100.0,
            self.direction,
            self.st_upper,
            ref="breakout",
            d_max=1.5,
            ext_max=1.0,
            fresh_bars=1,
        )
        self.assertEqual(kind, "E")
        self.assertAlmostEqual(value, 0.5)
        self.assertEqual(limit, 1.0)

        value, limit, kind = extension_value(
            4,
            106.0,
            2.0,
            103.0,
            self.direction,
            self.st_upper,
            ref="breakout",
            d_max=1.5,
            ext_max=1.0,
            fresh_bars=2,
        )
        self.assertEqual(kind, "D")
        self.assertAlmostEqual(value, 1.5)
        self.assertEqual(limit, 1.5)

    def test_st_line_mode(self):
        value, _, kind = extension_value(
            2,
            106.0,
            2.0,
            100.0,
            self.direction,
            self.st_upper,
            ref="st_line",
            d_max=1.5,
            ext_max=1.0,
            fresh_bars=10,
        )
        self.assertEqual(kind, "D")
        self.assertAlmostEqual(value, 3.0)


class ScoreModeTest(unittest.TestCase):
    def test_extension_penalty_uses_reference_range(self):
        cfg = ScoreConfig()
        self.assertAlmostEqual(
            _score(cfg, ext_value=1.5, ext_kind="E").p_ext, 0.5
        )
        self.assertAlmostEqual(
            _score(cfg, ext_value=1.5, ext_kind="D").p_ext, 0.5 / 3
        )

    def test_tick_mode_uses_tick_ranges(self):
        cfg = ScoreConfig()
        cfg.m1_lin_tick = (0.0, 1.0)
        self.assertAlmostEqual(
            _score(cfg, rti_3=2.0, feature_mode="tick").m1, 1.0
        )
        self.assertAlmostEqual(
            _score(cfg, rti_3=2.0, feature_mode="bar").m1, 1.0 / 2.58
        )


if __name__ == "__main__":
    unittest.main()
