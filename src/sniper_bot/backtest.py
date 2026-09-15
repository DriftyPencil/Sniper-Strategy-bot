from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import time
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sniper_bot.config import load_config
from sniper_bot.csv_loader import load_candles_csv
from sniper_bot.indicators import rsi
from sniper_bot.khansaab_indicator import KhanSaabBar
from sniper_bot.khansaab_indicator import calculate_khansaab_bars
from sniper_bot.market import Candle
from sniper_bot.strategy import Direction, Signal, SniperStrategy


@dataclass(frozen=True)
class Trade:
    direction: Direction
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    exit_reason: str
    pnl_points: float
    pnl_cash: float
    tp1_hit: bool
    tp2_hit: bool
    tp3_hit: bool
    active_stop_price: float
    bull_score: float
    bear_score: float
    bias: str
    ambiguous_exit_candles: int


@dataclass
class OpenTrade:
    signal: Signal
    entry_time: str
    remaining_fraction: float
    stop_price: float
    tp_hits: list[bool]
    realized_points: float
    exit_time: str
    exit_price: float
    exit_reason: str
    ambiguous_exit_candles: int = 0


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    starting_balance: float
    net_points: float
    net_cash: float
    profit_percent: float
    win_rate: float
    profit_factor: float
    max_drawdown_cash: float
    tp1_hit_rate: float
    tp2_hit_rate: float
    tp3_hit_rate: float
    ambiguous_exit_candles: int


def run_backtest(
    candles: list[Candle],
    strategy: SniperStrategy,
    size: float,
    starting_balance: float,
    from_time: str | None = None,
    to_time: str | None = None,
    rsi5m_candles: list[Candle] | None = None,
    entry_start_time: str | None = None,
    entry_end_time: str | None = None,
    entry_timezone: str = "UTC",
    allowed_entry_directions: set[Direction] | None = None,
    intrabar_policy: str = "stop_first",
) -> BacktestResult:
    trades: list[Trade] = []
    open_trade: OpenTrade | None = None
    start = _parse_optional_time(from_time)
    end = _parse_optional_time(to_time)
    entry_start = _parse_optional_clock(entry_start_time)
    entry_end = _parse_optional_clock(entry_end_time)
    entry_zone = ZoneInfo(entry_timezone)
    previous_in_window: Candle | None = None
    rsi5m_values = _aligned_previous_rsi_values(candles, rsi5m_candles)
    bars = calculate_khansaab_bars(candles, strategy.config, rsi5m_values)

    for bar in bars[1:]:
        current = bar.candle

        if end is not None and current.timestamp >= end:
            if open_trade is not None and previous_in_window is not None:
                _close_at_candle(open_trade, previous_in_window, "END_OF_WINDOW")
                trades.append(_close_trade(open_trade, size))
            break

        in_window = (start is None or current.timestamp >= start) and (end is None or current.timestamp < end)
        if in_window:
            previous_in_window = current

        entry_allowed = in_window and _entry_time_allowed(current.timestamp, entry_start, entry_end, entry_zone)
        signal = _signal_from_bar(bar, strategy) if in_window else None

        if open_trade is not None:
            if in_window:
                _update_open_trade(
                    current,
                    open_trade,
                    strategy.config.take_profit_allocations,
                    strategy.config.break_even_after_tp1,
                    intrabar_policy,
                )
            if open_trade.remaining_fraction <= 0:
                trades.append(_close_trade(open_trade, size))
                open_trade = None

            if (
                open_trade is not None
                and entry_allowed
                and signal is not None
                and signal.direction in {Direction.BUY, Direction.SELL}
                and signal.direction != open_trade.signal.direction
            ):
                _close_at_price(open_trade, current.timestamp, signal.entry_price, "OPPOSITE_SIGNAL")
                trades.append(_close_trade(open_trade, size))
                open_trade = _open_trade(signal, current) if _direction_allowed(signal.direction, allowed_entry_directions) else None
                continue

        if open_trade is not None or not entry_allowed or signal is None:
            continue

        if signal.direction in {Direction.BUY, Direction.SELL} and _direction_allowed(signal.direction, allowed_entry_directions):
            open_trade = _open_trade(signal, current)

    if open_trade is not None:
        final = previous_in_window or candles[-1]
        _close_at_candle(open_trade, final, "END_OF_DATA")
        trades.append(_close_trade(open_trade, size))

    return _summarize(trades, starting_balance)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the KhanSaab sniper indicator rules on OHLC CSV data.")
    parser.add_argument("csv_path", help="CSV with timestamp/open/high/low/close columns and optional volume/spread.")
    parser.add_argument("--spread", type=float, default=0.0, help="Default spread if the CSV has no spread column.")
    parser.add_argument("--size", type=float, default=None, help="Cash value per point. Defaults to DEFAULT_SIZE.")
    parser.add_argument("--from-time", default=None, help="Inclusive ISO timestamp filter, e.g. 2026-07-26T23:00:00+00:00.")
    parser.add_argument("--to-time", default=None, help="Exclusive ISO timestamp filter, e.g. 2026-07-27T23:00:00+00:00.")
    parser.add_argument("--rsi5m-csv", default=None, help="Optional 5-minute CSV used for KhanSaab's request.security 5m RSI.")
    parser.add_argument("--entry-start-time", default=None, help="Local clock time from which trades may open, e.g. 01:00.")
    parser.add_argument("--entry-end-time", default=None, help="Local clock time before which trades may open, e.g. 06:00.")
    parser.add_argument("--entry-timezone", default="UTC", help="Timezone for entry window. Default: UTC.")
    parser.add_argument("--directions", default="BUY,SELL", help="Comma-separated entry directions to take. Default: BUY,SELL.")
    parser.add_argument(
        "--intrabar-policy",
        choices=["stop_first", "target_first"],
        default="stop_first",
        help="How to handle candles that touch both SL and TP. Default: stop_first.",
    )
    parser.add_argument("--trades-out", default=None, help="Optional path to write the trade log CSV.")
    parser.add_argument("--summary-out", default=None, help="Optional path to write a JSON summary for dashboards.")
    args = parser.parse_args()

    config = load_config()
    candles = load_candles_csv(args.csv_path, default_spread=args.spread)
    rsi5m_candles = load_candles_csv(args.rsi5m_csv, default_spread=args.spread) if args.rsi5m_csv else None
    result = run_backtest(
        candles,
        SniperStrategy(config.strategy),
        args.size or config.strategy.default_size,
        config.strategy.starting_balance,
        args.from_time,
        args.to_time,
        rsi5m_candles,
        args.entry_start_time,
        args.entry_end_time,
        args.entry_timezone,
        _parse_directions(args.directions),
        args.intrabar_policy,
    )
    print_summary(result)
    if args.trades_out:
        write_trades_csv(result.trades, args.trades_out)
    if args.summary_out:
        write_summary_json(result, args.summary_out)


def print_summary(result: BacktestResult) -> None:
    print(f"Trades: {len(result.trades)}")
    print(f"Starting balance: {result.starting_balance:.2f}")
    print(f"Net points: {result.net_points:.5f}")
    print(f"Net cash: {result.net_cash:.2f}")
    print(f"Profit: {result.profit_percent:.3f}%")
    print(f"Win rate: {result.win_rate:.1f}%")
    print(f"Max drawdown cash: {result.max_drawdown_cash:.2f}")
    print(f"TP1 hit rate: {result.tp1_hit_rate:.1f}%")
    print(f"TP2 hit rate: {result.tp2_hit_rate:.1f}%")
    print(f"TP3 hit rate: {result.tp3_hit_rate:.1f}%")
    print(f"Ambiguous exit candles: {result.ambiguous_exit_candles}")


def write_trades_csv(trades: list[Trade], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(Trade.__dataclass_fields__.keys()))
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.__dict__)


def write_summary_json(result: BacktestResult, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    payload["profit_factor"] = _json_number(result.profit_factor)
    payload["trades"] = [
        {**asdict(trade), "direction": trade.direction.value}
        for trade in result.trades
    ]
    output.write_text(json.dumps(payload, indent=2))


def filter_candles(candles: list[Candle], from_time: str | None, to_time: str | None) -> list[Candle]:
    start = _parse_optional_time(from_time)
    end = _parse_optional_time(to_time)
    return [
        candle
        for candle in candles
        if (start is None or candle.timestamp >= start) and (end is None or candle.timestamp < end)
    ]


def chronological_split_bounds(
    candles: list[Candle],
    train_fraction: float = 0.8,
    from_time: str | None = None,
    to_time: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    scoped = filter_candles(candles, from_time, to_time)
    if len(scoped) < 2:
        raise ValueError("at least two candles are required for a chronological split")

    split_index = max(1, min(len(scoped) - 1, int(len(scoped) * train_fraction)))
    train_start = scoped[0].timestamp
    split_time = scoped[split_index].timestamp
    test_end = scoped[-1].timestamp
    return train_start, split_time, test_end


def _target_price(signal: Signal) -> float:
    if signal.target_prices:
        return signal.target_prices[min(2, len(signal.target_prices) - 1)]
    return signal.entry_price


def _update_open_trade(
    candle: Candle,
    trade: OpenTrade,
    allocations: list[float],
    break_even_after_tp1: bool,
    intrabar_policy: str,
) -> None:
    signal = trade.signal
    stop_hit = _stop_hit(candle, signal.direction, trade.stop_price)
    target_hits = [
        index < len(signal.target_prices)
        and not trade.tp_hits[index]
        and _target_hit(candle, signal.direction, signal.target_prices[index])
        for index in range(3)
    ]
    if stop_hit and any(target_hits):
        trade.ambiguous_exit_candles += 1

    if stop_hit and intrabar_policy == "stop_first":
        points = _pnl_points(signal.direction, signal.entry_price, trade.stop_price, signal.point_size)
        points = _round_points(points, signal)
        trade.realized_points += points * trade.remaining_fraction
        trade.exit_time = candle.timestamp.isoformat()
        trade.exit_price = trade.stop_price
        trade.exit_reason = "SL"
        trade.remaining_fraction = 0
        return

    for index, allocation in enumerate(allocations[:3]):
        if trade.tp_hits[index] or index >= len(signal.target_prices):
            continue
        target = signal.target_prices[index]
        if target_hits[index]:
            close_fraction = min(allocation, trade.remaining_fraction)
            points = _pnl_points(signal.direction, signal.entry_price, target, signal.point_size)
            points = _round_points(points, signal)
            trade.realized_points += points * close_fraction
            trade.remaining_fraction -= close_fraction
            trade.tp_hits[index] = True
            if index == 0 and break_even_after_tp1:
                trade.stop_price = signal.entry_price
            trade.exit_time = candle.timestamp.isoformat()
            trade.exit_price = target
            trade.exit_reason = f"TP{index + 1}"
            if trade.remaining_fraction <= 0:
                trade.exit_reason = "TP_PLAN_COMPLETE"
                return

    if stop_hit:
        points = _pnl_points(signal.direction, signal.entry_price, trade.stop_price, signal.point_size)
        points = _round_points(points, signal)
        trade.realized_points += points * trade.remaining_fraction
        trade.exit_time = candle.timestamp.isoformat()
        trade.exit_price = trade.stop_price
        trade.exit_reason = "SL"
        trade.remaining_fraction = 0


def _close_at_candle(trade: OpenTrade, candle: Candle, reason: str) -> None:
    exit_price = round(candle.close_mid, _level_decimals(trade.signal.entry_price))
    _close_at_price(trade, candle.timestamp, exit_price, reason)


def _close_at_price(trade: OpenTrade, timestamp: datetime, exit_price: float, reason: str) -> None:
    points = _pnl_points(trade.signal.direction, trade.signal.entry_price, exit_price, trade.signal.point_size)
    points = _round_points(points, trade.signal)
    trade.realized_points += points * trade.remaining_fraction
    trade.exit_time = timestamp.isoformat()
    trade.exit_price = exit_price
    trade.exit_reason = reason
    trade.remaining_fraction = 0


def _open_trade(signal: Signal, candle: Candle) -> OpenTrade:
    return OpenTrade(
        signal=signal,
        entry_time=candle.timestamp.isoformat(),
        remaining_fraction=1.0,
        stop_price=signal.stop_price,
        tp_hits=[False, False, False],
        realized_points=0.0,
        exit_time="",
        exit_price=signal.entry_price,
        exit_reason="",
    )


def _direction_allowed(direction: Direction, allowed_directions: set[Direction] | None) -> bool:
    if allowed_directions is None:
        return True
    return direction in allowed_directions


def _signal_from_bar(bar: KhanSaabBar, strategy: SniperStrategy) -> Signal:
    config = strategy.config
    entry_price = round(bar.entry_price, config.spread_bet_price_decimals)
    stop_price = round(bar.stop_price, config.spread_bet_price_decimals)
    target_prices = tuple(round(target, config.spread_bet_price_decimals) for target in bar.targets)

    if config.use_spread_filter and bar.candle.spread > config.max_spread_points:
        return Signal(
            Direction.HOLD,
            f"spread {bar.candle.spread:.5f} above limit",
            entry_price=entry_price,
            stop_price=stop_price,
            target_prices=target_prices,
            bull_score=bar.bull_score,
            bear_score=bar.bear_score,
            bias=bar.bias,
            status=bar.status,
            trend_strength=bar.trend_strength,
            setup_type="FILTERED",
        )

    if not bar.trigger_buy and not bar.trigger_sell:
        return Signal(
            Direction.HOLD,
            f"wait, bull_score={bar.bull_score:.0f}, bear_score={bar.bear_score:.0f}, bias={bar.bias}",
            entry_price=entry_price,
            stop_price=stop_price,
            target_prices=target_prices,
            bull_score=bar.bull_score,
            bear_score=bar.bear_score,
            bias=bar.bias,
            status=bar.status,
            trend_strength=bar.trend_strength,
            setup_type="WAIT",
        )

    risk = abs(entry_price - stop_price)
    target_distances = tuple(abs(target - entry_price) for target in target_prices)
    limit_distance = strategy._broker_limit_distance(target_distances)

    if bar.trigger_buy:
        if bar.bull_score <= config.min_bull_score_long:
            return Signal(
                Direction.HOLD,
                f"BUY blocked: bull_score={bar.bull_score:.0f} must be > {config.min_bull_score_long:.0f}",
                entry_price=entry_price,
                stop_price=stop_price,
                target_prices=target_prices,
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
            config.default_size,
            risk,
            limit_distance,
            target_distances,
            entry_price,
            stop_price,
            target_prices,
            bar.bull_score,
            bar.bear_score,
            bar.bias,
            bar.status,
            bar.trend_strength,
            "SIGNAL",
            config.spread_bet_point_size,
        )

    if bar.trigger_sell:
        bear_not_high_enough = bar.bear_score < config.min_bear_score_short
        bear_not_dominant = config.require_short_bear_dominance and bar.bear_score <= bar.bull_score
        if bear_not_high_enough or bear_not_dominant:
            return Signal(
                Direction.HOLD,
                f"SELL blocked: bear_score={bar.bear_score:.0f}, bull_score={bar.bull_score:.0f}",
                entry_price=entry_price,
                stop_price=stop_price,
                target_prices=target_prices,
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
            config.default_size,
            risk,
            limit_distance,
            target_distances,
            entry_price,
            stop_price,
            target_prices,
            bar.bull_score,
            bar.bear_score,
            bar.bias,
            bar.status,
            bar.trend_strength,
            "SIGNAL",
            config.spread_bet_point_size,
        )

    return Signal(Direction.HOLD, "no KhanSaab setup")


def _close_trade(trade: OpenTrade, size: float) -> Trade:
    return Trade(
        direction=trade.signal.direction,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        entry_price=trade.signal.entry_price,
        exit_price=trade.exit_price,
        stop_price=trade.signal.stop_price,
        target_price=_target_price(trade.signal),
        exit_reason=trade.exit_reason,
        pnl_points=trade.realized_points,
        pnl_cash=round(trade.realized_points * size, 2),
        tp1_hit=trade.tp_hits[0],
        tp2_hit=trade.tp_hits[1],
        tp3_hit=trade.tp_hits[2],
        active_stop_price=trade.stop_price,
        bull_score=trade.signal.bull_score,
        bear_score=trade.signal.bear_score,
        bias=trade.signal.bias,
        ambiguous_exit_candles=trade.ambiguous_exit_candles,
    )


def _stop_hit(candle: Candle, direction: Direction, stop_price: float) -> bool:
    if direction == Direction.BUY:
        return candle.low_mid <= stop_price
    if direction == Direction.SELL:
        return candle.high_mid >= stop_price
    return False


def _target_hit(candle: Candle, direction: Direction, target_price: float) -> bool:
    if direction == Direction.BUY:
        return candle.high_mid >= target_price
    if direction == Direction.SELL:
        return candle.low_mid <= target_price
    return False


def _pnl_points(direction: Direction, entry: float, exit_price: float, point_size: float = 1.0) -> float:
    if point_size <= 0:
        raise ValueError("point_size must be positive")
    if direction == Direction.BUY:
        price_move = exit_price - entry
    else:
        price_move = entry - exit_price
    return price_move / point_size


def _round_points(points: float, signal: Signal) -> float:
    return round(points, _level_decimals(signal.entry_price))


def _level_decimals(value: float) -> int:
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1])


def _summarize(trades: list[Trade], starting_balance: float = 10000) -> BacktestResult:
    net_points = sum(trade.pnl_points for trade in trades)
    net_cash = sum(trade.pnl_cash for trade in trades)
    profit_percent = (net_cash / starting_balance * 100) if starting_balance else 0.0
    winners = [trade.pnl_cash for trade in trades if trade.pnl_cash > 0]
    losers = [trade.pnl_cash for trade in trades if trade.pnl_cash < 0]
    win_rate = (len(winners) / len(trades) * 100) if trades else 0.0
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    return BacktestResult(
        trades=trades,
        starting_balance=starting_balance,
        net_points=net_points,
        net_cash=net_cash,
        profit_percent=profit_percent,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_cash=_max_drawdown_cash(trades),
        tp1_hit_rate=_hit_rate(trades, "tp1_hit"),
        tp2_hit_rate=_hit_rate(trades, "tp2_hit"),
        tp3_hit_rate=_hit_rate(trades, "tp3_hit"),
        ambiguous_exit_candles=sum(trade.ambiguous_exit_candles for trade in trades),
    )


def _hit_rate(trades: list[Trade], field: str) -> float:
    if not trades:
        return 0.0
    return sum(1 for trade in trades if getattr(trade, field)) / len(trades) * 100


def _max_drawdown_cash(trades: list[Trade]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_cash
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return abs(max_drawdown)


def _json_number(value: float) -> float | str:
    if math.isinf(value):
        return "Infinity"
    if math.isnan(value):
        return "NaN"
    return value


def _parse_optional_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_optional_clock(value: str | None) -> time | None:
    if not value:
        return None
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _parse_directions(value: str) -> set[Direction]:
    directions: set[Direction] = set()
    for item in value.split(","):
        name = item.strip().upper()
        if not name:
            continue
        if name not in {"BUY", "SELL"}:
            raise ValueError("--directions must contain BUY, SELL, or both")
        directions.add(Direction(name))
    if not directions:
        raise ValueError("--directions must contain at least one direction")
    return directions


def _entry_time_allowed(
    timestamp: datetime,
    entry_start: time | None,
    entry_end: time | None,
    entry_zone: ZoneInfo,
) -> bool:
    if entry_start is None and entry_end is None:
        return True
    local_time = timestamp.astimezone(entry_zone).time().replace(second=0, microsecond=0)
    if entry_start is None:
        return local_time < entry_end
    if entry_end is None:
        return local_time >= entry_start
    if entry_start <= entry_end:
        return entry_start <= local_time < entry_end
    return local_time >= entry_start or local_time < entry_end


def _build_previous_rsi_series(candles: list[Candle] | None) -> list[tuple[datetime, float]]:
    if not candles:
        return []
    values = rsi([candle.close_mid for candle in candles], 14)
    if not values:
        return []
    output: list[tuple[datetime, float]] = []
    for index, candle in enumerate(candles):
        previous_index = max(0, index - 1)
        output.append((candle.timestamp, values[previous_index]))
    return output


def _aligned_previous_rsi_values(candles: list[Candle], rsi5m_candles: list[Candle] | None) -> list[float] | None:
    if not rsi5m_candles:
        return None
    series = _build_previous_rsi_series(rsi5m_candles)
    if not series:
        return None
    output: list[float] = []
    series_index = 0
    latest = series[0][1]
    for candle in candles:
        while series_index < len(series) and series[series_index][0] <= candle.timestamp:
            latest = series[series_index][1]
            series_index += 1
        output.append(latest)
    return output


def _rsi_value_at_or_before(series: list[tuple[datetime, float]], timestamp: datetime) -> float | None:
    if not series:
        return None
    latest: float | None = None
    for item_time, value in series:
        if item_time > timestamp:
            break
        latest = value
    return latest


if __name__ == "__main__":
    main()
