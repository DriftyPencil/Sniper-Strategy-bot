from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

from sniper_bot.config import load_config
from sniper_bot.csv_loader import load_candles_csv
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


def run_backtest(
    candles: list[Candle],
    strategy: SniperStrategy,
    size: float,
    starting_balance: float,
    from_time: str | None = None,
    to_time: str | None = None,
) -> BacktestResult:
    trades: list[Trade] = []
    open_trade: OpenTrade | None = None
    start = _parse_optional_time(from_time)
    end = _parse_optional_time(to_time)
    previous_in_window: Candle | None = None

    for index in range(1, len(candles)):
        history = candles[: index + 1]
        current = candles[index]

        if end is not None and current.timestamp >= end:
            if open_trade is not None and previous_in_window is not None:
                _close_at_candle(open_trade, previous_in_window, "END_OF_WINDOW")
                trades.append(_close_trade(open_trade, size))
            break

        in_window = (start is None or current.timestamp >= start) and (end is None or current.timestamp < end)
        if in_window:
            previous_in_window = current

        if open_trade is not None:
            if in_window:
                _update_open_trade(current, open_trade, strategy.config.take_profit_allocations)
            if open_trade.remaining_fraction <= 0:
                trades.append(_close_trade(open_trade, size))
                open_trade = None
            continue

        if not in_window:
            continue

        signal = strategy.evaluate(history)
        if signal.direction in {Direction.BUY, Direction.SELL}:
            open_trade = OpenTrade(
                signal=signal,
                entry_time=current.timestamp.isoformat(),
                remaining_fraction=1.0,
                stop_price=signal.stop_price,
                tp_hits=[False, False, False],
                realized_points=0.0,
                exit_time="",
                exit_price=signal.entry_price,
                exit_reason="",
            )

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
    parser.add_argument("--trades-out", default=None, help="Optional path to write the trade log CSV.")
    parser.add_argument("--summary-out", default=None, help="Optional path to write a JSON summary for dashboards.")
    args = parser.parse_args()

    config = load_config()
    candles = load_candles_csv(args.csv_path, default_spread=args.spread)
    result = run_backtest(
        candles,
        SniperStrategy(config.strategy),
        args.size or config.strategy.default_size,
        config.strategy.starting_balance,
        args.from_time,
        args.to_time,
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


def _target_price(signal: Signal) -> float:
    if signal.target_prices:
        return signal.target_prices[min(2, len(signal.target_prices) - 1)]
    return signal.entry_price


def _update_open_trade(candle: Candle, trade: OpenTrade, allocations: list[float]) -> None:
    signal = trade.signal
    if _stop_hit(candle, signal.direction, trade.stop_price):
        points = _pnl_points(signal.direction, signal.entry_price, trade.stop_price)
        trade.realized_points += points * trade.remaining_fraction
        trade.exit_time = candle.timestamp.isoformat()
        trade.exit_price = trade.stop_price
        trade.exit_reason = "TRAIL_STOP" if trade.stop_price != signal.stop_price else "SL"
        trade.remaining_fraction = 0
        return

    for index, allocation in enumerate(allocations[:3]):
        if trade.tp_hits[index] or index >= len(signal.target_prices):
            continue
        target = signal.target_prices[index]
        if _target_hit(candle, signal.direction, target):
            close_fraction = min(allocation, trade.remaining_fraction)
            points = _pnl_points(signal.direction, signal.entry_price, target)
            trade.realized_points += points * close_fraction
            trade.remaining_fraction -= close_fraction
            trade.tp_hits[index] = True
            trade.exit_time = candle.timestamp.isoformat()
            trade.exit_price = target
            trade.exit_reason = f"TP{index + 1}"
            if trade.remaining_fraction <= 0:
                trade.exit_reason = "TP_PLAN_COMPLETE"
                return


def _close_at_candle(trade: OpenTrade, candle: Candle, reason: str) -> None:
    points = _pnl_points(trade.signal.direction, trade.signal.entry_price, candle.close_mid)
    trade.realized_points += points * trade.remaining_fraction
    trade.exit_time = candle.timestamp.isoformat()
    trade.exit_price = candle.close_mid
    trade.exit_reason = reason
    trade.remaining_fraction = 0


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
        pnl_cash=trade.realized_points * size,
        tp1_hit=trade.tp_hits[0],
        tp2_hit=trade.tp_hits[1],
        tp3_hit=trade.tp_hits[2],
        active_stop_price=trade.signal.stop_price,
        bull_score=trade.signal.bull_score,
        bear_score=trade.signal.bear_score,
        bias=trade.signal.bias,
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


def _pnl_points(direction: Direction, entry: float, exit_price: float) -> float:
    if direction == Direction.BUY:
        return exit_price - entry
    return entry - exit_price


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
    )


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


if __name__ == "__main__":
    main()
