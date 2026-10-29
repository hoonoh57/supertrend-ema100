from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import base_config, build_synthetic, force_trigger

from supertrend_ema100.backtest.metrics import compute_metrics, spearman
from supertrend_ema100.backtest.report import write_report
from supertrend_ema100.strategy.engine import BacktestEngine


class EngineTimingTest(unittest.TestCase):
    def _run(self, cfg, series):
        return BacktestEngine(cfg, series).run()

    def test_fill_is_next_bar_open_not_signal_close(self) -> None:
        cfg = base_config()
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        result = self._run(cfg, data)

        self.assertEqual(len(result.trades), 1, result.events)
        trade = result.trades[0]
        # T1 on bar 6, confirmation on bar 7, fill on bar 8's open.
        self.assertEqual(trade.signal_ts, series.bars[7].ts)
        self.assertEqual(trade.entry_ts, series.bars[8].ts)
        self.assertEqual(trade.entry_price, series.bars[8].open + cfg.risk.slip_ticks)
        self.assertEqual(trade.exit_ts, series.bars[11].ts)

        t1 = [e for e in result.events if e.kind == "T1"]
        entry = [e for e in result.events if e.kind == "ENTRY"]
        self.assertEqual(t1[0].ts, series.bars[6].ts)
        self.assertEqual(entry[0].ts, series.bars[7].ts)
        self.assertLess(entry[0].ts, trade.entry_ts)

    def test_stop_uses_bar_after_fill(self) -> None:
        cfg = base_config()
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        series.bars[9].low = 90.0
        result = self._run(cfg, data)

        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "X_STOP")
        self.assertEqual(trade.exit_ts, series.bars[9].ts)
        self.assertLess(trade.r_multiple, 0)

    def test_day_end_forces_exit(self) -> None:
        cfg = base_config()
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        result = self._run(cfg, data)

        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "X_EOD")
        self.assertEqual(trade.exit_ts, series.bars[11].ts)

    def test_no_entry_when_fill_would_cross_days(self) -> None:
        cfg = base_config()
        series, data = build_synthetic(cfg)
        force_trigger(series, 10)  # confirm on the last bar of day 1
        result = self._run(cfg, data)

        self.assertEqual(result.trades, [])
        self.assertTrue(
            any(e.kind == "REJECT" and e.note == "overnight" for e in result.events)
        )

    def test_deferred_signal_creates_counterfactual_trade(self) -> None:
        cfg = base_config()
        cfg.delay.bar_ret_pct = 0.0  # force the F_BAR delay filter
        cfg.exits.eod_exit = "09:09"
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        result = self._run(cfg, data)

        self.assertEqual(result.trades, [])
        self.assertEqual(len(result.virtual_trades), 1)
        virtual = result.virtual_trades[0]
        self.assertEqual(virtual.deferred_reasons, "BAR")
        self.assertEqual(virtual.entry_ts, series.bars[7].ts)
        self.assertEqual(virtual.exit_reason, "X_EOD")
        self.assertEqual(virtual.exit_ts, series.bars[9].ts)
        self.assertGreaterEqual(virtual.hold_bars, 1)

    def test_score_drop_alert_while_holding(self) -> None:
        from dataclasses import replace

        from supertrend_ema100.indicators.score import EMPTY_SCORE

        cfg = base_config()
        cfg.score.enabled = True
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        high = replace(EMPTY_SCORE, score=80.0, grade="A", p_div=0.0)
        low = replace(EMPTY_SCORE, score=40.0, grade="C", p_div=0.3)
        series.scores = [high] * 10 + [low] * (len(series.bars) - 10)

        result = self._run(cfg, data)
        alerts = [e for e in result.events if e.kind == "SCORE_DROP"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("entry=80.0", alerts[0].note)
        self.assertIn("now=40.0", alerts[0].note)

    def test_eod_time_close(self) -> None:
        cfg = base_config()
        cfg.exits.eod_exit = "09:05"
        series, data = build_synthetic(cfg)
        force_trigger(series, 1)
        result = self._run(cfg, data)
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "X_EOD")
        # Decision at 09:05 close, fill at the 09:06 open.
        self.assertEqual(trade.exit_ts, series.bars[5].ts)
        self.assertEqual(trade.exit_price, series.bars[5].open - cfg.risk.slip_ticks)


class MetricsReportTest(unittest.TestCase):
    def test_metrics_and_files(self) -> None:
        cfg = base_config()
        series, data = build_synthetic(cfg)
        force_trigger(series, 6)
        result = BacktestEngine(cfg, data).run()
        metrics = compute_metrics(result)

        self.assertEqual(metrics["overall"]["trades"], 1)
        self.assertIn("equity", metrics)
        self.assertEqual(metrics["data"]["start_date"], data.start_date)
        self.assertIsInstance(metrics["counterfactual_filters"], list)

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_report(result, metrics, tmp, plot=True)
            for key in (
                "trades",
                "signals",
                "counterfactual",
                "virtual_trades",
                "equity",
                "metrics",
                "config",
                "summary",
                "plot",
            ):
                self.assertTrue(Path(paths[key]).exists(), key)
            with open(paths["trades"], encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 1)
            loaded = json.loads(Path(paths["metrics"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["overall"]["trades"], 1)

    def test_spearman(self) -> None:
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) or 0, 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) or 0, -1.0)
        self.assertIsNone(spearman([1, 2], [2, 1]))


if __name__ == "__main__":
    unittest.main()
