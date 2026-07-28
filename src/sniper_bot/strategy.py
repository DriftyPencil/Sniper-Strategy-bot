from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sniper_bot.config import StrategyConfig
from sniper_bot.khansaab_indicator import calculate_khansaab_bars
from sniper_bot.market import Candle


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    direction: Direction
    reason: str
    size: float = 0
    stop_distance: float = 0
    limit_distance: float = 0
    target_distances: tuple[float, ...] = ()
    entry_price: float = 0
    stop_price: float = 0
    target_prices: tuple[float, ...] = ()
    bull_score: float = 0
    bear_score: float = 0
    bias: str = "NONE"
    status: str = "WAIT"
    trend_strength: str = "WEAK"
    setup_type: str = "NONE"


class SniperStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def evaluate(self, candles: list[Candle], rsi_5m_value: float | None = None) -> Signal:
        minimum = 50
        if len(candles) < minimum:
            return Signal(Direction.HOLD, f"need at least {minimum} candles")

        latest = candles[-1]
        if self.config.use_spread_filter and latest.spread > self.config.max_spread_points:
            return Signal(Direction.HOLD, f"spread {latest.spread:.5f} above limit")

        bars = calculate_khansaab_bars(candles, self.config)
        if not bars:
            return Signal(Direction.HOLD, "indicators not ready")
        bar = bars[-1]

        if not bar.trigger_buy and not bar.trigger_sell:
            retest_text = " retest" if bar.is_retest else ""
            target_distances = tuple(abs(target - bar.entry_price) for target in bar.targets)
            return Signal(
                Direction.HOLD,
                f"wait{retest_text}, bull_score={bar.bull_score:.0f}, bear_score={bar.bear_score:.0f}, bias={bar.bias}",
                target_distances=target_distances,
                entry_price=bar.entry_price,
                stop_price=bar.stop_price,
                target_prices=bar.targets,
                bull_score=bar.bull_score,
                bear_score=bar.bear_score,
                bias=bar.bias,
                status=bar.status,
                trend_strength=bar.trend_strength,
                setup_type="RETEST" if bar.is_retest else "WAIT",
            )

        risk = abs(bar.entry_price - bar.stop_price)
        target_distances = tuple(abs(target - bar.entry_price) for target in bar.targets)
        limit_distance = self._broker_limit_distance(target_distances)

        if bar.trigger_buy:
            if bar.bull_score <= self.config.min_bull_score_long:
                return Signal(
                    Direction.HOLD,
                    f"BUY blocked: bull_score={bar.bull_score:.0f} must be > {self.config.min_bull_score_long:.0f}",
                    entry_price=bar.entry_price,
                    stop_price=bar.stop_price,
                    target_prices=bar.targets,
                    bull_score=bar.bull_score,
                    bear_score=bar.bear_score,
                    bias=bar.bias,
                    status=bar.status,
                    trend_strength=bar.trend_strength,
                    setup_type="FILTERED",
                )
            return Signal(
                Direction.BUY,
                f"BUY EMA cross, bull_score={bar.bull_score:.0f}, bear_score={bar.bear_score:.0f}, bias={bar.bias}",
                self.config.default_size,
                risk,
                limit_distance,
                target_distances,
                bar.entry_price,
                bar.stop_price,
                bar.targets,
                bar.bull_score,
                bar.bear_score,
                bar.bias,
                bar.status,
                bar.trend_strength,
                "SIGNAL",
            )

        if bar.trigger_sell:
            bear_not_high_enough = bar.bear_score < self.config.min_bear_score_short
            bear_not_dominant = self.config.require_short_bear_dominance and bar.bear_score <= bar.bull_score
            if bear_not_high_enough or bear_not_dominant:
                return Signal(
                    Direction.HOLD,
                    f"SELL blocked: bear_score={bar.bear_score:.0f}, bull_score={bar.bull_score:.0f}",
                    entry_price=bar.entry_price,
                    stop_price=bar.stop_price,
                    target_prices=bar.targets,
                    bull_score=bar.bull_score,
                    bear_score=bar.bear_score,
                    bias=bar.bias,
                    status=bar.status,
                    trend_strength=bar.trend_strength,
                    setup_type="FILTERED",
                )
            return Signal(
                Direction.SELL,
                f"SELL EMA cross, bull_score={bar.bull_score:.0f}, bear_score={bar.bear_score:.0f}, bias={bar.bias}",
                self.config.default_size,
                risk,
                limit_distance,
                target_distances,
                bar.entry_price,
                bar.stop_price,
                bar.targets,
                bar.bull_score,
                bar.bear_score,
                bar.bias,
                bar.status,
                bar.trend_strength,
                "SIGNAL",
            )

        return Signal(
            Direction.HOLD,
            "no KhanSaab setup",
            bull_score=bar.bull_score,
            bear_score=bar.bear_score,
            bias=bar.bias,
            status=bar.status,
            trend_strength=bar.trend_strength,
        )

    def _broker_limit_distance(self, target_distances: tuple[float, ...]) -> float:
        if not target_distances:
            return 0
        index = max(1, min(self.config.broker_target_index, len(target_distances))) - 1
        return target_distances[index]
