from __future__ import annotations

import argparse
import logging

from sniper_bot.config import load_config
from sniper_bot.csv_loader import write_candles_csv


LOGGER = logging.getLogger("sniper_bot.download_prices")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download IG historical prices to CSV.")
    parser.add_argument(
        "epic",
        nargs="?",
        help="IG market EPIC. Defaults to the first value in MARKET_EPICS.",
    )
    parser.add_argument(
        "--resolution",
        default="MINUTE_5",
        help="IG price resolution. Default: MINUTE_5.",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=1000,
        help="Number of candles to request. Default: 1000.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output CSV path. Default: data/<epic>_<resolution>.csv.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from sniper_bot.ig_client import IGClient

    config = load_config()
    epic = args.epic or config.strategy.market_epics[0]
    output = args.out or f"data/{_safe_filename(epic)}_{args.resolution.lower()}.csv"

    client = IGClient(config.ig)
    LOGGER.info("downloading epic=%s resolution=%s points=%s", epic, args.resolution, args.points)
    candles = client.historical_prices(epic, args.resolution, args.points)
    if not candles:
        raise RuntimeError("IG returned no candles for this request")

    write_candles_csv(candles, output)
    first = candles[0].timestamp.isoformat()
    last = candles[-1].timestamp.isoformat()
    LOGGER.info("wrote %s candles to %s (%s -> %s)", len(candles), output, first, last)


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


if __name__ == "__main__":
    main()
