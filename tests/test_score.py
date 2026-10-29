from __future__ import annotations

import unittest

from supertrend_ema100.config import ScoreConfig
from supertrend_ema100.indicators.score import compute_score, lin, tri


BASE_KWARGS = dict(
    close=102.0,
    vwap=100.0,
    sigma_eff=1.0,
    vwap_slope_atr=0.5,
    above_vwap_ratio=1.0,
    rti_3=6.0,
    accel=2.5,
    buy_ratio=0.7,
    er_tick=0.4,
    atv_ratio=2.0,
    tov=50.0,
    tov_p50=10.0,
    tov_p95=50.0,
    st_line=101.5,
    atr=1.0,
    vi_up=None,
    grade_multipliers={"A": 1.0, "B": 0.6, "C": 0.0},
)


class NormalizationTest(unittest.TestCase):
    def test_lin(self) -> None:
        self.assertEqual(lin(0, 0, 1), 0.0)
        self.assertEqual(lin(0.5, 0, 1), 0.5)
        self.assertEqual(lin(2, 0, 1), 1.0)
        self.assertEqual(lin(None, 0, 1), 0.0)

    def test_tri(self) -> None:
        self.assertEqual(tri(0.0, 0, 0.5, 2.0, 3.5), 0.0)
        self.assertAlmostEqual(tri(0.25, 0, 0.5, 2.0, 3.5), 0.5)
        self.assertEqual(tri(1.0, 0, 0.5, 2.0, 3.5), 1.0)
        self.assertEqual(tri(3.5, 0, 0.5, 2.0, 3.5), 0.0)


class ScoreTest(unittest.TestCase):
    def test_perfect_components_score_100(self) -> None:
        result = compute_score(ScoreConfig(), **BASE_KWARGS)
        self.assertAlmostEqual(result.u, 1.0)
        self.assertAlmostEqual(result.m, 1.0)
        self.assertAlmostEqual(result.p, 1.0)
        self.assertAlmostEqual(result.score, 100.0)
        self.assertEqual(result.grade, "A")
        self.assertEqual(result.multiplier, 1.0)

    def test_penalty_extension(self) -> None:
        result = compute_score(ScoreConfig(), **{**BASE_KWARGS, "st_line": 99.0})
        # D = 3 ATR -> lin(3, 1, 2.5) = 1 -> p_ext = 0.5
        self.assertAlmostEqual(result.p_ext, 0.5)
        self.assertAlmostEqual(result.p, 0.5)
        self.assertAlmostEqual(result.score, 50.0)
        self.assertEqual(result.grade, "B")
        self.assertEqual(result.multiplier, 0.6)

    def test_min_component_zeroes_score(self) -> None:
        result = compute_score(
            ScoreConfig(), **{**BASE_KWARGS, "vwap": 120.0, "above_vwap_ratio": 0.0}
        )
        self.assertLess(result.u, 0.3)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.grade, "C")
        self.assertEqual(result.multiplier, 0.0)

    def test_geo_mode(self) -> None:
        cfg = ScoreConfig(mode="geo")
        result = compute_score(cfg, **BASE_KWARGS)
        self.assertAlmostEqual(result.score, 100.0)

    def test_disabled_score_is_neutral(self) -> None:
        cfg = ScoreConfig(enabled=False)
        result = compute_score(cfg, **BASE_KWARGS)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.grade, "-")
        self.assertEqual(result.multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()
