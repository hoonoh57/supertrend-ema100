from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import base_config, build_synthetic, force_trigger

from supertrend_ema100.cli import build_config, build_parser
from supertrend_ema100.config import BacktestConfig
from supertrend_ema100.data.universe import (
    capture_minute,
    load_universe,
    parse_hhmmss,
    watch_phase,
)
from supertrend_ema100.strategy.engine import BacktestEngine
from supertrend_ema100.strategy.state_machine import State, SymbolStateMachine


class UniverseTest(unittest.TestCase):
    def test_parse_times_and_round_capture_up(self) -> None:
        self.assertEqual(parse_hhmmss("0903"), 9 * 3600 + 180)
        self.assertEqual(parse_hhmmss("09:02:30"), 9 * 3600 + 150)
        self.assertEqual(capture_minute(9 * 3600 + 150), 9 * 60 + 3)
        self.assertEqual(capture_minute(9 * 3600 + 180), 9 * 60 + 3)
        with self.assertRaises(ValueError):
            parse_hhmmss("0960")

    def test_first_capture_and_window(self) -> None:
        text = (
            "date,code,time\n"
            "2026-10-29,A079650,09:02:30\n"
            "20261029,079650,09:10:00\n"
            "20261029,000660,09:15:00\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.csv"
            path.write_text(text, encoding="utf-8")
            universe = load_universe(str(path), "0900", "0903")
        self.assertEqual(universe, {"079650": {"20261029": 9 * 3600 + 150}})

    def test_watch_phase(self) -> None:
        watch_start = 9 * 60 + 3
        self.assertEqual(watch_phase(None, "20261029", 9 * 60 + 2, watch_start), "pre")
        self.assertEqual(watch_phase(None, "20261029", 9 * 60 + 3, watch_start), "live")
        capture = {"20261029": 9 * 3600 + 310}
        self.assertEqual(watch_phase(capture, "20261028", 9 * 60 + 30, watch_start), "off")
        self.assertEqual(watch_phase(capture, "20261029", 9 * 60 + 5, watch_start), "pre")
        self.assertEqual(watch_phase(capture, "20261029", 9 * 60 + 6, watch_start), "live")

    def test_cli_universe_sets_symbols_and_date_span(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.csv"
            path.write_text(
                "date,code,time\n20261029,000660,090212\n"
                "20261030,079650,090230\n",
                encoding="utf-8",
            )
            args = build_parser().parse_args(["backtest", "--universe", str(path)])
            cfg = build_config(args)
        self.assertEqual(cfg.data.symbols, ["000660", "079650"])
        self.assertEqual(cfg.data.start, "20261029")
        self.assertEqual(cfg.data.end, "20261030")

    def test_universe_settings_validate(self) -> None:
        cfg = BacktestConfig()
        cfg.universe.prewatch_trigger = "invalid"
        with self.assertRaisesRegex(ValueError, "prewatch_trigger"):
            cfg.validate()


class PrewatchStateMachineTest(unittest.TestCase):
    def _machine_at_prewatch(self, mode: str):
        cfg = base_config()
        cfg.universe.watch_start = "0905"
        cfg.universe.prewatch_trigger = mode
        series, _ = build_synthetic(cfg, prices=[100.0] * 12)
        force_trigger(series, 2)
        machine = SymbolStateMachine(series)
        events, intent = machine.on_bar(2, cfg)
        self.assertIsNone(intent)
        return cfg, series, machine, events

    def test_prewatch_t1_is_deferred_and_logged(self) -> None:
        _, _, machine, events = self._machine_at_prewatch("defer")
        self.assertEqual(machine.state, State.DEFERRED)
        self.assertEqual([(event.kind, event.reasons) for event in events], [("T1", ["PREWATCH"])])

    def test_defer_waits_until_a_later_rearm(self) -> None:
        cfg, series, machine, _ = self._machine_at_prewatch("defer")
        machine.on_bar(3, cfg)
        machine.on_bar(4, cfg)
        self.assertEqual(machine.state, State.DEFERRED)

        series.direction[4] = -1
        series.direction[5] = 1
        events, _ = machine.on_bar(5, cfg)
        self.assertEqual(machine.state, State.PENDING)
        self.assertEqual(events[0].kind, "REARM")

    def test_carry_allows_still_valid_setup_at_watch_start(self) -> None:
        cfg, _, machine, _ = self._machine_at_prewatch("carry")
        machine.on_bar(3, cfg)
        events, _ = machine.on_bar(4, cfg)
        self.assertEqual(machine.state, State.PENDING)
        self.assertEqual(events[0].kind, "REARM")

    def test_prewatch_event_is_counterfactual_without_real_entry(self) -> None:
        cfg = base_config()
        cfg.universe.watch_start = "0905"
        series, data = build_synthetic(cfg, prices=[100.0] * 12)
        force_trigger(series, 2)

        result = BacktestEngine(cfg, data).run()

        self.assertEqual(result.trades, [])
        self.assertTrue(any(event.reasons == ["PREWATCH"] for event in result.events))
        self.assertTrue(result.virtual_trades)

    def test_ignore_discards_prewatch_t1(self) -> None:
        cfg, _, machine, events = self._machine_at_prewatch("ignore")
        self.assertEqual(machine.state, State.IDLE)
        self.assertEqual(events, [])
        machine.on_bar(4, cfg)
        self.assertEqual(machine.state, State.IDLE)


if __name__ == "__main__":
    unittest.main()
