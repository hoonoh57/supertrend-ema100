from __future__ import annotations

import unittest

from supertrend_ema100.config import BacktestConfig


class ConfigTest(unittest.TestCase):
    def test_nested_override(self) -> None:
        cfg = BacktestConfig.from_dict(
            {"delay": {"d_max": 1.2}, "score": {"enabled": False}, "data": {"days": 5}}
        )
        self.assertAlmostEqual(cfg.delay.d_max, 1.2)
        self.assertFalse(cfg.score.enabled)
        self.assertEqual(cfg.data.days, 5)
        # untouched values keep their defaults
        self.assertEqual(cfg.indicators.atr_len, 14)

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BacktestConfig.from_dict({"delay": {"d_maxx": 1.0}})
        with self.assertRaises(ValueError):
            BacktestConfig.from_dict({"nope": 1})

    def test_validate_catches_bad_values(self) -> None:
        cfg = BacktestConfig()
        cfg.data.feature_mode = "magic"
        with self.assertRaises(ValueError):
            cfg.validate()

        cfg = BacktestConfig()
        cfg.score.u_weights = (0.5, 0.5, 0.5)
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_tuple_and_bool_coercion(self) -> None:
        cfg = BacktestConfig.from_dict(
            {
                "score": {"u1_tri": [0, 0.4, 1.8, 3.0]},
                "plot": "true",
            }
        )
        self.assertEqual(cfg.score.u1_tri, (0, 0.4, 1.8, 3.0))
        self.assertTrue(cfg.plot)

    def test_roundtrip(self) -> None:
        cfg = BacktestConfig()
        cfg.delay.d_max = 1.7
        again = BacktestConfig.from_dict(cfg.to_dict())
        self.assertEqual(again.delay.d_max, 1.7)
        self.assertEqual(again.to_dict()["risk"], cfg.to_dict()["risk"])


if __name__ == "__main__":
    unittest.main()
