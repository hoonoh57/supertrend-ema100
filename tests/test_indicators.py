from __future__ import annotations

import math
import unittest

from supertrend_ema100.indicators.basic import (
    atr_wilder,
    ema,
    jma,
    rsi,
    round_to_tick,
    session_vwap,
    supertrend,
    tick_size,
    true_range,
)
from supertrend_ema100.kiwoom.models import Bar


def bar(ts: str, o: float, h: float, l: float, c: float, v: float = 1.0) -> Bar:
    return Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v, value=c * v)


def labels(count: int, day: str = "20260102", start: int = 541) -> list[str]:
    return [
        day + f"{(start + i) // 60:02d}{(start + i) % 60:02d}" for i in range(count)
    ]


class TickSizeTest(unittest.TestCase):
    def test_brackets(self) -> None:
        cases = {
            100: 1,
            1999: 1,
            2000: 5,
            4999: 5,
            5000: 10,
            19999: 10,
            20000: 50,
            49999: 50,
            50000: 100,
            199999: 100,
            200000: 500,
            499999: 500,
            500000: 1000,
            1_000_000: 1000,
        }
        for price, expected in cases.items():
            self.assertEqual(tick_size(price), expected, price)

    def test_round(self) -> None:
        self.assertEqual(round_to_tick(2001), 2000)
        self.assertEqual(round_to_tick(2003), 2005)
        self.assertEqual(round_to_tick(0), 0.0)


class AtrTest(unittest.TestCase):
    def test_constant_range(self) -> None:
        bars = [bar(ts, 100, 101, 99, 100) for ts in labels(20)]
        atr = atr_wilder(bars, 14)
        for value in atr[13:]:
            self.assertAlmostEqual(value, 2.0, places=9)

    def test_gap_included(self) -> None:
        bars = [
            bar(labels(1)[0], 100, 101, 99, 100),
            bar(labels(2)[1], 110, 112, 109, 111),
        ]
        tr = true_range(bars)
        self.assertAlmostEqual(tr[1], 12.0, places=9)


class EmaTest(unittest.TestCase):
    def test_recurrence(self) -> None:
        out = ema([1.0, 2.0, 3.0], 2)
        self.assertAlmostEqual(out[0], 1.0)
        self.assertAlmostEqual(out[1], 2 / 3 * 2 + 1 / 3 * 1)
        self.assertAlmostEqual(out[2], 2 / 3 * 3 + 1 / 3 * out[1])


class SuperTrendTest(unittest.TestCase):
    def test_uptrend_then_break(self) -> None:
        prices = [100 + i for i in range(30)] + [100.0]
        bars = [
            bar(labels(len(prices))[i], p, p + 0.5, p - 0.5, p)
            for i, p in enumerate(prices)
        ]
        result = supertrend(bars, 14, 2.0)
        self.assertEqual(result.direction[28], 1)
        self.assertLess(result.st[28], prices[28])
        self.assertEqual(result.direction[-1], -1)
        self.assertGreater(result.st[-1], prices[-1])
        self.assertFalse(result.ready[5])
        self.assertTrue(result.ready[20])


class JmaTest(unittest.TestCase):
    def test_warmup_mean_then_smooth(self) -> None:
        values = [10.0, 11.0, 12.0, 13.0, 12.0, 11.0]
        result = jma(values, 3, 50, 2)
        self.assertEqual(result.values[0], 10.0)
        self.assertEqual(result.values[1], 10.5)
        self.assertEqual(result.values[2], 11.0)
        self.assertEqual(len(result.values), len(values))
        self.assertTrue(all(d in (-1, 1) for d in result.direction))


class RsiTest(unittest.TestCase):
    def test_monotonic_rise_is_100(self) -> None:
        values = [float(i) for i in range(1, 30)]
        out = rsi(values, 14)
        self.assertIsNone(out[13])
        self.assertAlmostEqual(out[14], 100.0)

    def test_bounds(self) -> None:
        values = [100 + math.sin(i / 3) * 5 for i in range(100)]
        out = rsi(values, 14)
        for value in out[14:]:
            self.assertIsNotNone(value)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)


class VwapTest(unittest.TestCase):
    def test_resets_each_day(self) -> None:
        day1 = [bar(ts, 100, 101, 99, 100, 10) for ts in labels(5, "20260102")]
        day2 = [bar(ts, 200, 202, 198, 200, 10) for ts in labels(5, "20260105")]
        result = session_vwap(day1 + day2, 0.003)
        self.assertAlmostEqual(result.vwap[0], 100.0, places=6)
        self.assertAlmostEqual(result.vwap[5], 200.0, places=6)
        self.assertAlmostEqual(result.sigma_eff[0], 2.0, places=6)  # 2 x tick size


if __name__ == "__main__":
    unittest.main()
