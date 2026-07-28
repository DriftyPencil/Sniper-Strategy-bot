from __future__ import annotations

import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sniper_bot.backtest import _pnl_points, _summarize, filter_candles, write_summary_json
from sniper_bot.market import Candle
from sniper_bot.strategy import Direction


class BacktestTests(unittest.TestCase):
    def test_buy_pnl_points(self) -> None:
        self.assertAlmostEqual(_pnl_points(Direction.BUY, 1.1000, 1.1015), 0.0015)

    def test_sell_pnl_points(self) -> None:
        self.assertAlmostEqual(_pnl_points(Direction.SELL, 1.1000, 1.0980), 0.0020)

    def test_empty_summary(self) -> None:
        result = _summarize([])
        self.assertEqual(result.net_cash, 0)
        self.assertEqual(result.win_rate, 0)

    def test_summary_json_is_written(self) -> None:
        result = _summarize([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            write_summary_json(result, path)
            payload = json.loads(path.read_text())

        self.assertEqual(payload["net_cash"], 0)
        self.assertEqual(payload["trades"], [])

    def test_filter_candles(self) -> None:
        candles = [
            Candle(datetime(2026, 7, 26, 22, 55, tzinfo=timezone.utc), 1, 1, 1, 1, 1, 1, 1, 1),
            Candle(datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc), 2, 2, 2, 2, 2, 2, 2, 2),
            Candle(datetime(2026, 7, 27, 23, 0, tzinfo=timezone.utc), 3, 3, 3, 3, 3, 3, 3, 3),
        ]
        filtered = filter_candles(candles, "2026-07-26T23:00:00+00:00", "2026-07-27T23:00:00+00:00")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].open_mid, 2)


if __name__ == "__main__":
    unittest.main()
