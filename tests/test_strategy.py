from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sniper_bot.config import StrategyConfig
from sniper_bot.market import Candle
from sniper_bot.strategy import Direction, SniperStrategy


def config() -> StrategyConfig:
    return StrategyConfig(
        market_epics=["TEST"],
        resolution="MINUTE_5",
        price_points=80,
        max_spread_points=0.0004,
        fast_ema=9,
        slow_ema=21,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        score_threshold=0,
        min_risk_reward=1.0,
        stop_atr_multiple=1.5,
        target_multiples=[1, 2, 3, 4, 5],
        broker_target_index=2,
        default_size=0.5,
    )


def candle(index: int, close: float, spread: float = 0.0002) -> Candle:
    bid = close - spread / 2
    ask = close + spread / 2
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * index)
    return Candle(ts, bid, ask, bid + 0.0004, ask + 0.0004, bid - 0.0004, ask - 0.0004, bid, ask)


class StrategyTests(unittest.TestCase):
    def test_holds_when_not_enough_candles(self) -> None:
        signal = SniperStrategy(config()).evaluate([candle(0, 1.1)])
        self.assertEqual(signal.direction, Direction.HOLD)

    def test_holds_when_spread_is_too_wide(self) -> None:
        candles = [candle(i, 1.10 + i * 0.0001) for i in range(40)]
        candles[-1] = candle(40, 1.105, spread=0.001)
        signal = SniperStrategy(config()).evaluate(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertIn("spread", signal.reason)


if __name__ == "__main__":
    unittest.main()
