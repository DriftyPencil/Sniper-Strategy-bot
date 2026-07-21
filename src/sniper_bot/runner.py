from __future__ import annotations

import argparse
import logging
import time

from sniper_bot.config import load_config
from sniper_bot.config import AppConfig
from sniper_bot.indicators import rsi
from sniper_bot.ig_client import IGClient
from sniper_bot.strategy import Direction, SniperStrategy


LOGGER = logging.getLogger("sniper_bot")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the IG sniper strategy bot.")
    parser.add_argument("--once", action="store_true", help="Evaluate every configured market once and exit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = IGClient(config.ig)
    strategy = SniperStrategy(config.strategy)

    LOGGER.info("starting sniper bot env=%s dry_run=%s", config.ig.environment, config.runtime.dry_run)
    while True:
        run_cycle(client, strategy, config)
        if args.once:
            return
        time.sleep(config.runtime.poll_seconds)


def run_cycle(client: IGClient, strategy: SniperStrategy, config: AppConfig) -> None:
    positions = client.open_positions()
    for epic in config.strategy.market_epics:
        try:
            candles = client.historical_prices(epic, config.strategy.resolution, config.strategy.price_points)
            signal = strategy.evaluate(candles, _five_minute_rsi(client, epic, config))
            LOGGER.info("%s signal=%s reason=%s", epic, signal.direction, signal.reason)

            if signal.direction == Direction.HOLD:
                continue
            if _has_open_position(positions, epic, signal.direction):
                LOGGER.info("%s skipped because matching position is already open", epic)
                continue
            if config.runtime.dry_run:
                LOGGER.info(
                    "%s dry-run order direction=%s setup=%s size=%s stop=%s limit=%s targets=%s",
                    epic,
                    signal.direction,
                    signal.setup_type,
                    signal.size,
                    signal.stop_distance,
                    signal.limit_distance,
                    signal.target_distances,
                )
                continue

            response = client.create_market_position(
                epic=epic,
                direction=signal.direction.value,
                size=signal.size,
                stop_distance=signal.stop_distance,
                limit_distance=signal.limit_distance,
            )
            LOGGER.info("%s order submitted response=%s", epic, response)
        except Exception:
            LOGGER.exception("%s cycle failed", epic)


def _has_open_position(positions: list[dict], epic: str, direction: Direction) -> bool:
    for item in positions:
        market = item.get("market", {})
        position = item.get("position", {})
        if market.get("epic") == epic and position.get("direction") == direction.value:
            return True
    return False


def _five_minute_rsi(client: IGClient, epic: str, config: AppConfig) -> float | None:
    if config.strategy.resolution == "MINUTE_5":
        return None
    candles = client.historical_prices(epic, "MINUTE_5", max(config.strategy.rsi_period + 5, 30))
    values = rsi([candle.close_mid for candle in candles], config.strategy.rsi_period)
    if not values:
        return None
    return values[-1]
