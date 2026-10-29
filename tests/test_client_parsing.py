from __future__ import annotations

import unittest

from supertrend_ema100.kiwoom.client import KiwoomClient


class ParsingTest(unittest.TestCase):
    def test_normalize_code(self) -> None:
        self.assertEqual(KiwoomClient.normalize_code("5930"), "005930")
        self.assertEqual(KiwoomClient.normalize_code("A005930"), "005930")
        self.assertEqual(KiwoomClient.normalize_code("005930_AL"), "005930")
        self.assertEqual(KiwoomClient.normalize_code("KRX-005930"), "005930")

    def test_daily_row_scales_million_krw(self) -> None:
        row = {
            "dt": "20261028",
            "open_pric": "70000",
            "high_pric": "71000",
            "low_pric": "69000",
            "cur_prc": "-70500",
            "trde_qty": "12345",
            "trde_prica": "1234",
        }
        bar = KiwoomClient.parse_daily_row(row)
        assert bar is not None
        self.assertEqual(bar.date, "20261028")
        self.assertEqual(bar.close, 70500.0)
        self.assertEqual(bar.value, 1_234_000_000.0)
        self.assertEqual(bar.volume, 12345.0)

    def test_minute_row(self) -> None:
        row = {
            "cntr_tm": "20261028090100",
            "open_pric": "70000",
            "high_pric": "70100",
            "low_pric": "69900",
            "cur_prc": "70050",
            "trde_qty": "100",
        }
        bar = KiwoomClient.parse_minute_row(row)
        assert bar is not None
        self.assertEqual(bar.ts, "202610280901")
        self.assertEqual(bar.day, "20261028")
        self.assertEqual(bar.minute_of_day, 9 * 60 + 1)
        self.assertAlmostEqual(bar.value, (70100 + 69900 + 70050) / 3 * 100)

    def test_short_row_rejected(self) -> None:
        self.assertIsNone(KiwoomClient.parse_minute_row({"cntr_tm": "0901"}))
        self.assertIsNone(KiwoomClient.parse_daily_row({"dt": "2026"}))


if __name__ == "__main__":
    unittest.main()
