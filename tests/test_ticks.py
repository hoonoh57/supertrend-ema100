from __future__ import annotations

import unittest

from supertrend_ema100.data.ticks import bar_duration_seconds, build_bars_from_ticks
from supertrend_ema100.kiwoom.models import Tick


def tick(ts: str, price: float, volume: float) -> Tick:
    return Tick(ts=ts, price=price, volume=volume)


class TickBarBuilderTest(unittest.TestCase):
    def test_sign_inference_and_aggregation(self) -> None:
        ticks = [
            tick("20260102085900", 99.0, 100),  # pre-session, excluded
            tick("20260102090100", 100.0, 10),
            tick("20260102090110", 101.0, 5),
            tick("20260102090120", 100.0, 3),
            tick("20260102090200", 100.0, 2),  # equal price carries last sign
        ]
        bars = build_bars_from_ticks(ticks)
        self.assertEqual(len(bars), 2)

        first = bars[0]
        self.assertEqual(first.ts, "202601020901")
        self.assertEqual(first.open, 100.0)
        self.assertEqual(first.high, 101.0)
        self.assertEqual(first.low, 100.0)
        self.assertEqual(first.close, 100.0)
        self.assertEqual(first.n_ticks, 3.0)
        self.assertEqual(first.buy_vol, 15.0)
        self.assertEqual(first.sell_vol, 3.0)
        self.assertEqual(first.volume, 18.0)
        self.assertEqual(first.value, 100 * 10 + 101 * 5 + 100 * 3)
        self.assertEqual(first.path_len, 2.0)
        self.assertEqual(first.p_first, 100.0)
        self.assertEqual(first.p_last, 100.0)

        second = bars[1]
        self.assertEqual(second.n_ticks, 1.0)
        self.assertEqual(second.buy_vol, 0.0)
        self.assertEqual(second.sell_vol, 2.0)

    def test_vi_flag_and_session(self) -> None:
        ticks = [
            tick("20260102090000", 100.0, 1),
            tick("20260102090100", 100.0, 1),
            tick("20260102152100", 100.0, 1),  # after session end
        ]
        bars = build_bars_from_ticks(ticks, vi_minutes=["202601020901"])
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars[0].vi_flag)
        self.assertTrue(bars[0].has_tick_fields)

    def test_n_tick_duration(self) -> None:
        ticks = [tick(f"202601020901{i:02d}", 100.0, 1) for i in range(35)]
        self.assertEqual(bar_duration_seconds(ticks, "202601020901", 30), 29.0)
        self.assertIsNone(bar_duration_seconds(ticks, "202601020901", 40))


if __name__ == "__main__":
    unittest.main()
