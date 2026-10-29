from __future__ import annotations

import unittest

from supertrend_ema100.strategy.filters import confirm_checks

from .helpers import base_config, build_synthetic


class RiskConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = base_config()
        self.series, _ = build_synthetic(self.cfg, prices=[10_000.0] * 12)
        self.index = 0

    def test_risk_confirmation_is_disabled_by_default(self) -> None:
        result = confirm_checks(self.series, self.index, self.cfg)

        self.assertFalse(self.cfg.confirm.use_risk)
        self.assertNotIn("K_RISK", result.checks)

    def test_risk_confirmation_rejects_narrow_stop(self) -> None:
        self.cfg.confirm.use_risk = True
        self.series.st[self.index] = 9_960.0

        result = confirm_checks(self.series, self.index, self.cfg)

        self.assertFalse(result.checks["K_RISK"])
        self.assertFalse(result.passed)

    def test_risk_confirmation_accepts_sufficient_stop_width(self) -> None:
        self.cfg.confirm.use_risk = True
        self.series.st[self.index] = 9_900.0

        result = confirm_checks(self.series, self.index, self.cfg)

        self.assertTrue(result.checks["K_RISK"])
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
