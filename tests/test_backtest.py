from __future__ import annotations

import unittest

from sniper_bot.backtest import _pnl_points, _summarize
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


if __name__ == "__main__":
    unittest.main()
