from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sniper_bot.config import StrategyConfig
from sniper_bot.indicators import adx, atr, ema, macd, rsi, session_vwap, sma
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
    setup_type: str = "NONE"


class SniperStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def evaluate(self, candles: list[Candle], rsi_5m_value: float | None = None) -> Signal:
        minimum = max(self.config.macd_slow + self.config.macd_signal, self.config.adx_period * 2) + 5
        if len(candles) < minimum:
            return Signal(Direction.HOLD, f"need at least {minimum} candles")

        latest = candles[-1]
        if latest.spread > self.config.max_spread_points:
            return Signal(Direction.HOLD, f"spread {latest.spread:.5f} above limit")

        closes = [candle.close_mid for candle in candles]
        volumes = [candle.volume for candle in candles]
        fast = ema(closes, self.config.fast_ema)
        slow = ema(closes, self.config.slow_ema)
        momentum = rsi(closes, self.config.rsi_period)
        volatility = atr(candles, self.config.atr_period)
        trend_strength = adx(candles, self.config.adx_period)
        macd_line, macd_signal_line, _ = macd(
            closes,
            self.config.macd_fast,
            self.config.macd_slow,
            self.config.macd_signal,
        )
        vwap = session_vwap(candles)
        vol_avg = sma(volumes, 20)

        if not momentum or not volatility or not trend_strength or not macd_signal_line:
            return Signal(Direction.HOLD, "indicators not ready")

        fast_now = fast[-1]
        fast_previous = fast[-2]
        slow_now = slow[-1]
        slow_previous = slow[-2]
        rsi_now = momentum[-1]
        rsi_5m = rsi_now if rsi_5m_value is None else rsi_5m_value
        atr_now = volatility[-1]
        adx_now = trend_strength[-1]
        vwap_now = vwap[-1]
        bullish_cross = fast_previous <= slow_previous and fast_now > slow_now
        bearish_cross = fast_previous >= slow_previous and fast_now < slow_now
        last_signal_state = self._last_signal_state(fast, slow)
        trigger_buy = bullish_cross and last_signal_state <= 0
        trigger_sell = bearish_cross and last_signal_state >= 0
        is_retest = (
            (last_signal_state == 1 and latest.low_mid <= fast_now and latest.low_mid > slow_now)
            or (last_signal_state == -1 and latest.high_mid >= fast_now and latest.high_mid < slow_now)
        )

        bull_score, bear_score = self._dashboard_scores(
            latest=latest,
            rsi_now=rsi_now,
            rsi_5m=rsi_5m,
            macd_main=macd_line[-1],
            macd_signal=macd_signal_line[-1],
            adx_now=adx_now,
            vwap_now=vwap_now,
            ema9=fast_now,
            ema21=slow_now,
            vol_avg=vol_avg[-1],
        )
        bias = self._bias_text(bull_score, bear_score)

        if not trigger_buy and not trigger_sell:
            retest_text = " retest" if is_retest else ""
            return Signal(
                Direction.HOLD,
                f"wait{retest_text}, bull_score={bull_score:.0f}, bear_score={bear_score:.0f}, bias={bias}",
                bull_score=bull_score,
                bear_score=bear_score,
                bias=bias,
                setup_type="RETEST" if is_retest else "WAIT",
            )

        if max(bull_score, bear_score) < self.config.score_threshold:
            return Signal(
                Direction.HOLD,
                f"score below threshold, bull_score={bull_score:.0f}, bear_score={bear_score:.0f}",
                bull_score=bull_score,
                bear_score=bear_score,
                bias=bias,
            )

        entry_price = latest.close_mid
        risk = atr_now * self.config.stop_atr_multiple
        target_distances = tuple(risk * multiple for multiple in self.config.target_multiples)
        limit_distance = self._broker_limit_distance(target_distances)

        if risk <= 0 or limit_distance / risk < self.config.min_risk_reward:
            return Signal(Direction.HOLD, "risk/reward filter failed", bull_score=bull_score, bear_score=bear_score, bias=bias)

        if trigger_buy:
            return Signal(
                Direction.BUY,
                f"BUY EMA cross, bull_score={bull_score:.0f}, bear_score={bear_score:.0f}, bias={bias}",
                self.config.default_size,
                risk,
                limit_distance,
                target_distances,
                entry_price,
                entry_price - risk,
                tuple(entry_price + distance for distance in target_distances),
                bull_score,
                bear_score,
                bias,
                "SIGNAL",
            )

        if trigger_sell:
            return Signal(
                Direction.SELL,
                f"SELL EMA cross, bull_score={bull_score:.0f}, bear_score={bear_score:.0f}, bias={bias}",
                self.config.default_size,
                risk,
                limit_distance,
                target_distances,
                entry_price,
                entry_price + risk,
                tuple(entry_price - distance for distance in target_distances),
                bull_score,
                bear_score,
                bias,
                "SIGNAL",
            )

        return Signal(Direction.HOLD, "no KhanSaab setup", bull_score=bull_score, bear_score=bear_score, bias=bias)

    def _broker_limit_distance(self, target_distances: tuple[float, ...]) -> float:
        if not target_distances:
            return 0
        index = max(1, min(self.config.broker_target_index, len(target_distances))) - 1
        return target_distances[index]

    def _dashboard_scores(
        self,
        *,
        latest: Candle,
        rsi_now: float,
        rsi_5m: float,
        macd_main: float,
        macd_signal: float,
        adx_now: float,
        vwap_now: float,
        ema9: float,
        ema21: float,
        vol_avg: float,
    ) -> tuple[float, float]:
        bull_checks = [
            latest.close_mid > vwap_now,
            rsi_now > 50,
            macd_main > macd_signal,
            ema9 > ema21,
            adx_now > 25 and latest.close_mid > ema9,
            latest.volume > vol_avg and latest.close_mid > latest.open_mid,
            rsi_5m > 50,
        ]
        bear_checks = [
            latest.close_mid < vwap_now,
            rsi_now < 50,
            macd_main < macd_signal,
            ema9 < ema21,
            adx_now > 25 and latest.close_mid < ema9,
            latest.volume > vol_avg and latest.close_mid < latest.open_mid,
            rsi_5m < 50,
        ]
        return self._score(bull_checks), self._score(bear_checks)

    def _score(self, checks: list[bool]) -> float:
        return (sum(1 for check in checks if check) / len(checks)) * 100

    def _last_signal_state(self, fast: list[float], slow: list[float]) -> int:
        state = 0
        for index in range(1, len(fast) - 1):
            if fast[index - 1] <= slow[index - 1] and fast[index] > slow[index] and state <= 0:
                state = 1
            elif fast[index - 1] >= slow[index - 1] and fast[index] < slow[index] and state >= 0:
                state = -1
        return state

    def _bias_text(self, bull_score: float, bear_score: float) -> str:
        if bull_score - bear_score >= 40:
            return "STRONG BULL"
        if bear_score - bull_score >= 40:
            return "STRONG BEAR"
        if bull_score > bear_score:
            return "MILD BULL"
        return "MILD BEAR"
